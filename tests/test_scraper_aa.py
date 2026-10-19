import ast
import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import Mock, patch

import pandas as pd

import scraper_aa
from scripts.firebase_upload import _build_payloads

ROOT = Path(__file__).resolve().parents[1]


def model(slug="gpt-5-4", score=38.9756):
    return dict(id=slug, slug=slug, name=slug, release_date="2026-03-05",
                model_creator=dict(name="OpenAI", slug="openai"),
                evaluations=dict(artificial_analysis_intelligence_index=score), pricing={})


def page(models):
    return dict(status=200, prompt_options={}, data=models)


def pipeline_functions():
    # update.py runs uploads at module scope. Compile only the pure functions
    # under test so tests cannot scrape, email, or access production Firebase.
    names = {'extract_numeric_score', 'match_source_score', 'append_history', 'build_sources_json', 'check_tracking_status', 'get_untracked_models', 'normalize_model_name'}
    tree = ast.parse((ROOT / 'update.py').read_text())
    selected = ast.Module(body=[n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in names], type_ignores=[])
    import re
    metadata = ['aa_estimated', 'aa_version', 'aa_slug']
    scope = dict(pd=pd, json=json, re=re, datetime=datetime, AA_METADATA=metadata,
                 HISTORY_COLUMNS=['date', 'model', 'lma', 'aa', 'lb', *metadata],
                 _load_history_from_firebase=lambda: None, print_step=lambda *args: None)
    exec(compile(selected, str(ROOT / 'update.py'), 'exec'), scope)
    return scope


class ArtificialAnalysisTests(unittest.TestCase):
    def test_api_rows_rounding_and_metadata(self):
        df = scraper_aa.parse_models(page([model(), model('mini', 24.5), model('zero', 0), model('missing', None)]))
        self.assertEqual(df['Intelligence Index'].tolist(), [39, 25, 0])
        self.assertTrue(df.aa_estimated.isna().all())
        self.assertEqual(df.aa_version.tolist(), [''] * 3)
        self.assertEqual(df.aa_slug.tolist(), ['gpt-5-4', 'mini', 'zero'])
        self.assertEqual(df.Creator.tolist(), ['OpenAI'] * 3)

    def test_invalid_scores_fail(self):
        for value in [True, '39', -1, 101, float('nan'), float('inf')]:
            with self.subTest(value=value), self.assertRaises(RuntimeError):
                scraper_aa.parse_models(page([model(score=value)]))

    def test_duplicate_or_missing_identity_fails(self):
        nameless = model(); nameless['name'] = ''
        for models in [[model(), model()], [nameless]]:
            with self.subTest(models=models), self.assertRaises(RuntimeError):
                scraper_aa.parse_models(page(models))

    def test_schema_change_fails(self):
        no_index = model(); no_index['evaluations'] = {'new_index': 39}
        no_creator = model(); del no_creator['model_creator']
        for payload in [{'status': 200, 'models': []}, {'status': 500, 'data': [model()]}, page([no_index]), page([no_creator]), page([]), []]:
            with self.subTest(payload=str(payload)[:60]), self.assertRaises(RuntimeError):
                scraper_aa.parse_models(payload)

    def test_missing_key_stops_scrape_without_request(self):
        with patch.dict(scraper_aa.os.environ, {'AA_API_KEY': ''}), patch.object(scraper_aa.requests, 'get') as get, self.assertRaises(RuntimeError):
            scraper_aa.scrape()
        get.assert_not_called()

    def test_http_error_stops_scrape(self):
        response = Mock(status_code=401)
        with patch.dict(scraper_aa.os.environ, {'AA_API_KEY': 'test-key'}), patch.object(scraper_aa.requests, 'get', return_value=response), self.assertRaises(RuntimeError):
            scraper_aa.scrape()

    def test_http_scrape_uses_one_request_with_key_header(self):
        response = Mock(status_code=200)
        response.json.return_value = page([model()])
        with patch.dict(scraper_aa.os.environ, {'AA_API_KEY': 'test-key'}), patch.object(scraper_aa.requests, 'get', return_value=response) as get:
            self.assertEqual(scraper_aa.scrape().iloc[0]['Intelligence Index'], 39)
            get.assert_called_once_with(scraper_aa.URL, headers={'x-api-key': 'test-key'}, timeout=(10, 45))

    def test_source_export_and_exact_variant_matching(self):
        funcs = pipeline_functions()
        df = scraper_aa.parse_models(page([model()]))
        df.loc[0, 'Model'] = 'GPT-5.4 (Xhigh)'
        match = funcs['match_source_score']
        self.assertEqual(match(df, 'gpt-5-4', ['slug'], ['index']), 39)
        self.assertIsNone(match(df, 'gpt-5-4-high', ['slug'], ['index']))
        self.assertIsNone(match(df, 'GPT-5.4 (Xhigh)', ['slug'], ['index']))
        tracking = pd.DataFrame([dict(model='gpt54', name='GPT 5.4', logo='gpt', geo='US', aa_lookup='GPT-5.4 (xhigh)', aa_slug='gpt-5-4')])
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp); (path / 'models.json').write_text('[]')
            sources = funcs['build_sources_json'](None, df, None, tracking, path / 'models.json', path / 'sources.json')
            row = sources['aa'][0]
            self.assertEqual((row['id'], row['score'], row['aa_estimated'], row['aa_slug']), ('gpt54', 39, None, 'gpt-5-4'))

    def test_history_and_firebase_preserve_metadata_only_changes(self):
        funcs = pipeline_functions()
        result = pd.DataFrame([dict(model='gpt54', lma=1477, aa=39, lb=77.97,
                                    aa_estimated=1, aa_version='v4.3', aa_slug='gpt-5-4')])
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp); (base / 'data').mkdir(); history = base / 'data/history.csv'
            history.write_text('date;model;lma;aa;lb\n2026-01-01;gpt54;1477;39;77.97\n')
            append = funcs['append_history']
            self.assertEqual(append(result, history), 1)
            self.assertEqual(append(result, history), 0)
            result.loc[0, 'aa_estimated'] = 0
            self.assertEqual(append(result, history), 1)
            result.loc[0, 'aa_version'] = 'v4.4'
            self.assertEqual(append(result, history), 1)
            result.loc[0, 'aa_version'] = ''
            self.assertEqual(append(result, history), 0)
            self.assertEqual(append(result, history), 0)
            result.loc[0, 'aa_version'] = 'v4.4'
            result.to_csv(base / 'data/processed.csv', sep=';', index=False)
            payloads = _build_payloads(base)
            self.assertIsNone(payloads['history'][0]['aa_estimated'])
            self.assertEqual(payloads['history'][1]['aa_estimated'], 1)
            self.assertEqual(payloads['history'][-1]['aa_version'], 'v4.4')
            self.assertEqual(payloads['processed'][0]['aa_estimated'], 0)


    def test_unknown_estimate_is_stable_and_untracked_check_uses_slug(self):
        funcs = pipeline_functions()
        result = pd.DataFrame([dict(model='gpt54', lma=1477, aa=39, lb=77.97,
                                    aa_estimated=None, aa_version='', aa_slug='gpt-5-4')])
        with tempfile.TemporaryDirectory() as tmp:
            history = Path(tmp) / 'history.csv'
            history.write_text('date;model;lma;aa;lb;aa_estimated;aa_version;aa_slug\n2026-01-01;gpt54;1477;39;77.97;0;v4.3;gpt-5-4\n')
            self.assertEqual(funcs['append_history'](result, history), 1)
            self.assertEqual(funcs['append_history'](result, history), 0)
        df = scraper_aa.parse_models(page([model(), model('new-model', 50)]))
        df['Model'] = ['GPT-5.4 (Xhigh)', 'New Model']
        tracking = pd.DataFrame([dict(model='gpt54', name='GPT 5.4', aa_lookup='GPT-5.4 (xhigh)', aa_slug='gpt-5-4')])
        untracked = funcs['get_untracked_models'](df, 'Artificial Analysis', ['index'], tracking, 'aa_slug', match_col='aa_slug')
        self.assertEqual([u['raw_name'] for u in untracked], ['New Model'])


if __name__ == '__main__':
    unittest.main()
