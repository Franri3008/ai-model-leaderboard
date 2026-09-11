import ast
import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import Mock, patch

import pandas as pd
import requests

import scraper_aa
from scripts.firebase_upload import _build_payloads

ROOT = Path(__file__).resolve().parents[1]


def model(slug="gpt-5-4", score=38.9756, estimated=True):
    return dict(slug=slug, shortName=slug, intelligenceIndex=score,
                intelligenceIndexIsEstimated=estimated, modelCreatorName="OpenAI",
                deprecated=True)


def page(models):
    stream = 'a:' + json.dumps({"models": [{"slug": "navigation-only"}]}) + '\nb:' + json.dumps({"models": models})
    # Deliberately split in the middle of a JSON string.
    split = stream.index('intelligenceIndex') + 6
    scripts = ''.join('<script>self.__next_f.push(' + json.dumps([1, part]) + ')</script>'
                      for part in (stream[:split], stream[split:]))
    return '<h1>Updated to Intelligence Index v4.3</h1>' + scripts


def pipeline_functions():
    # update.py runs uploads at module scope. Compile only the pure functions
    # under test so tests cannot scrape, email, or access production Firebase.
    names = {'extract_numeric_score', 'match_source_score', 'append_history', 'build_sources_json'}
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
    def test_split_payload_deprecated_estimated_and_rounding(self):
        df = scraper_aa.parse_models(page([model(), model('mini', 24.5, False), model('zero', 0, False), model('missing', None)]))
        self.assertEqual(df['Intelligence Index'].tolist(), [39, 25, 0])
        self.assertEqual(df.aa_estimated.tolist(), [1, 0, 0])
        self.assertEqual(df.aa_version.tolist(), ['v4.3'] * 3)
        self.assertEqual(df.aa_slug.tolist(), ['gpt-5-4', 'mini', 'zero'])

    def test_invalid_scores_fail(self):
        for value in [True, '39', -1, 101, float('nan'), float('inf')]:
            with self.subTest(value=value), self.assertRaises(RuntimeError):
                scraper_aa.parse_models(page([model(score=value)]))

    def test_missing_estimate_flag_and_duplicate_identity_fail(self):
        broken = model(); del broken['intelligenceIndexIsEstimated']
        for models in [[broken], [model(), model()], [model(estimated=None)]]:
            with self.subTest(models=models), self.assertRaises(RuntimeError):
                scraper_aa.parse_models(page(models))

    def test_schema_change_does_not_fall_back_to_visible_table(self):
        for html in ['<table><tr><td>39</td></tr></table>', page([model()]).replace('intelligenceIndex', 'newIndex'), page([model()]).replace('v4.3', '')]:
            with self.subTest(html=html[:60]), self.assertRaises(RuntimeError):
                scraper_aa.parse_models(html)

    def test_http_error_stops_scrape(self):
        response = Mock()
        response.raise_for_status.side_effect = requests.HTTPError('503')
        with patch.object(scraper_aa.requests, 'get', return_value=response), self.assertRaises(requests.HTTPError):
            scraper_aa.scrape()

    def test_http_scrape_uses_one_request(self):
        response = Mock(text=page([model()]))
        with patch.object(scraper_aa.requests, 'get', return_value=response) as get:
            self.assertEqual(scraper_aa.scrape().iloc[0]['Intelligence Index'], 39)
            get.assert_called_once_with(scraper_aa.URL, timeout=(10, 45))

    def test_source_export_and_exact_variant_matching(self):
        funcs = pipeline_functions()
        df = scraper_aa.parse_models(page([model()]))
        match = funcs['match_source_score']
        self.assertEqual(match(df, 'gpt-5-4', ['model'], ['index']), 39)
        self.assertIsNone(match(df, 'gpt-5-4-high', ['model'], ['index']))
        tracking = pd.DataFrame([dict(model='gpt54', name='GPT 5.4', logo='gpt', geo='US', aa_lookup='gpt-5-4')])
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp); (path / 'models.json').write_text('[]')
            sources = funcs['build_sources_json'](None, df, None, tracking, path / 'models.json', path / 'sources.json')
            row = sources['aa'][0]
            self.assertEqual((row['id'], row['score'], row['aa_estimated'], row['aa_version']), ('gpt54', 39, 1, 'v4.3'))

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
            result.to_csv(base / 'data/processed.csv', sep=';', index=False)
            payloads = _build_payloads(base)
            self.assertIsNone(payloads['history'][0]['aa_estimated'])
            self.assertEqual(payloads['history'][1]['aa_estimated'], 1)
            self.assertEqual(payloads['history'][-1]['aa_version'], 'v4.4')
            self.assertEqual(payloads['processed'][0]['aa_estimated'], 0)


if __name__ == '__main__':
    unittest.main()
