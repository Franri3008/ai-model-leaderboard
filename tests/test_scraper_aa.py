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


def page(models, number=1, total=1, tier='free', version=5):
    return dict(tier=tier, intelligence_index_version=version, data=models,
                pagination=dict(page=number, page_size=200, total_pages=total, has_more=number < total))


def parse(models, version=5):
    return scraper_aa.parse_models(models, version)


def reply(payload=None, status=200, headers=None):
    response = Mock(status_code=status, headers=headers or {})
    response.json.return_value = payload if payload is not None else {'error': f'error {status}'}
    return response


def fake_api(routes):
    calls = []

    def get(url, headers, params, timeout):
        calls.append((url, params['page']))
        return routes[(url, params['page'])]
    return get, calls


def paged(models, size, url=None, tier='free'):
    url = url or scraper_aa.URL
    chunks = [models[i:i + size] for i in range(0, len(models), size)] or [[]]
    return {(url, n + 1): reply(page(chunk, n + 1, len(chunks), tier)) for n, chunk in enumerate(chunks)}


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
        no_creator = model('anon', 12); no_creator['model_creator'] = None
        df = parse([model(), model('mini', 24.5), model('zero', 0), model('missing', None), no_creator], 5)
        self.assertEqual(df['Intelligence Index'].tolist(), [39, 25, 0, 12])
        self.assertTrue(df.aa_estimated.isna().all())
        self.assertEqual(df.aa_version.tolist(), ['v5.0'] * 4)
        self.assertEqual(parse([model()], 4.1).aa_version.tolist(), ['v4.1'])
        self.assertEqual(df.aa_slug.tolist(), ['gpt-5-4', 'mini', 'zero', 'anon'])
        self.assertEqual(df.Creator.tolist(), ['OpenAI'] * 3 + [''])

    def test_invalid_scores_fail(self):
        for value in [True, '39', -1, 101, float('nan'), float('inf')]:
            with self.subTest(value=value), self.assertRaises(RuntimeError):
                parse([model(score=value)])

    def test_duplicate_or_missing_identity_fails(self):
        nameless = model(); nameless['name'] = ''
        for models in [[model(), model()], [nameless]]:
            with self.subTest(models=models), self.assertRaises(RuntimeError):
                parse(models)

    def test_model_schema_change_fails(self):
        no_index = model(); no_index['evaluations'] = {'new_index': 39}
        no_creator = model(); del no_creator['model_creator']
        bad_creator = model(); bad_creator['model_creator'] = 'OpenAI'
        for models in [[no_index], [no_creator], [bad_creator], [], ['gpt-5-4']]:
            with self.subTest(models=str(models)[:60]), self.assertRaises(RuntimeError):
                parse(models)

    def test_page_schema_change_fails(self):
        legacy = dict(status=200, prompt_options={}, data=[model()])
        no_pagination = page([model()]); del no_pagination['pagination']
        no_version = page([model()]); del no_version['intelligence_index_version']
        bad_tier = page([model()], tier='enterprise')
        bad_more = page([model()]); bad_more['pagination']['has_more'] = 'no'
        empty_but_more = page([], 1, 3)
        stopped_early = page([model()], 1, 3); stopped_early['pagination']['has_more'] = False
        for payload in [legacy, no_pagination, no_version, bad_tier, bad_more, empty_but_more, stopped_early, []]:
            with self.subTest(payload=str(payload)[:60]), self.assertRaises(RuntimeError):
                scraper_aa.check_page(payload, 1)
        with self.assertRaisesRegex(RuntimeError, 'page 2 when page 1'):
            scraper_aa.check_page(page([model()], 2, 3), 1)
        self.assertEqual(scraper_aa.check_page(page([model()], 2, 3), 2)['data'][0]['slug'], 'gpt-5-4')

    def test_missing_key_stops_scrape_without_request(self):
        with patch.dict(scraper_aa.os.environ, {'AA_API_KEY': ''}), patch.object(scraper_aa.requests, 'get') as get, self.assertRaises(RuntimeError):
            scraper_aa.scrape()
        get.assert_not_called()

    def run_scrape(self, routes, minimum=1, previous=None, previous_version=None, new_minimum=1):
        get, calls = fake_api(routes)
        with patch.dict(scraper_aa.os.environ, {'AA_API_KEY': 'test-key'}), patch.object(scraper_aa.requests, 'get', side_effect=get) as mock_get, \
                patch.object(scraper_aa, 'MIN_SCORED_MODELS', minimum), patch.object(scraper_aa, 'MIN_SCORED_NEW_INDEX', new_minimum), \
                patch.object(scraper_aa, 'previous_run', return_value=(previous, previous_version)):
            try:
                return scraper_aa.scrape(), calls, mock_get
            except RuntimeError as exc:
                exc.calls = calls
                raise

    def test_http_errors_stop_scrape(self):
        for status, text in [(401, 'AA_API_KEY missing or invalid'), (410, 'retired'), (429, 'retry after 3600s'), (500, 'HTTP 500')]:
            with self.subTest(status=status), self.assertRaisesRegex(RuntimeError, text) as ctx:
                self.run_scrape({(scraper_aa.URL, 1): reply(status=status, headers={'Retry-After': '3600'})})
            self.assertEqual(ctx.exception.calls, [(scraper_aa.URL, 1)])

    def test_invalid_json_stops_scrape(self):
        broken = reply(); broken.json.side_effect = ValueError('bad')
        with self.assertRaisesRegex(RuntimeError, 'invalid JSON on page 1'):
            self.run_scrape({(scraper_aa.URL, 1): broken})

    def test_pro_request_uses_key_header_and_page_param(self):
        df, calls, get = self.run_scrape({(scraper_aa.URL, 1): reply(page([model()], tier='pro'))})
        self.assertEqual(df.iloc[0]['Intelligence Index'], 39)
        get.assert_called_once_with(scraper_aa.URL, headers={'x-api-key': 'test-key'}, params={'page': 1}, timeout=(10, 45))

    def test_follows_every_page_until_list_ends(self):
        models = [model(f'm{i}', 50) for i in range(704)]
        df, calls, _ = self.run_scrape(paged(models, 200, tier='pro'))
        self.assertEqual(calls, [(scraper_aa.URL, n) for n in (1, 2, 3, 4)])
        self.assertEqual(len(df), 704)
        self.assertEqual(df.aa_slug.iloc[-1], 'm703')

    def test_duplicate_slug_across_pages_fails(self):
        routes = {(scraper_aa.URL, 1): reply(page([model('a')], 1, 2, 'pro')), (scraper_aa.URL, 2): reply(page([model('a')], 2, 2, 'pro'))}
        with self.assertRaisesRegex(RuntimeError, 'duplicated'):
            self.run_scrape(routes)

    def test_pages_must_agree_on_version_and_tier(self):
        for second in [page([model('b')], 2, 2, 'pro', 4.1), page([model('b')], 2, 2, 'free')]:
            routes = {(scraper_aa.URL, 1): reply(page([model('a')], 1, 2, 'pro')), (scraper_aa.URL, 2): reply(second)}
            with self.subTest(second=second['tier']), self.assertRaisesRegex(RuntimeError, 'disagree'):
                self.run_scrape(routes)

    def test_error_on_later_page_stops_scrape(self):
        routes = {(scraper_aa.URL, 1): reply(page([model('a')], 1, 2, 'pro')), (scraper_aa.URL, 2): reply(status=500)}
        with self.assertRaisesRegex(RuntimeError, 'HTTP 500 .* page 2'):
            self.run_scrape(routes)

    def test_page_cap_stops_endless_paging(self):
        routes = {(scraper_aa.URL, n): reply(page([model(f'm{n}')], n, 10_000, 'pro')) for n in range(1, scraper_aa.MAX_PAGES + 2)}
        with self.assertRaisesRegex(RuntimeError, f'after {scraper_aa.MAX_PAGES} pages') as ctx:
            self.run_scrape(routes)
        self.assertEqual(len(ctx.exception.calls), scraper_aa.MAX_PAGES)

    def test_forbidden_pro_falls_back_to_free_list(self):
        models = [model(f'm{i}', 50) for i in range(250)]
        routes = {(scraper_aa.URL, 1): reply({'error': 'Language models list requires a Pro subscription'}, 403), **paged(models, 200, scraper_aa.FREE_URL)}
        df, calls, _ = self.run_scrape(routes)
        self.assertEqual(calls, [(scraper_aa.URL, 1), (scraper_aa.FREE_URL, 1), (scraper_aa.FREE_URL, 2)])
        self.assertEqual(len(df), 250)

    def test_free_list_error_after_fallback_stops_scrape(self):
        routes = {(scraper_aa.URL, 1): reply(status=403), (scraper_aa.FREE_URL, 1): reply(status=401)}
        with self.assertRaisesRegex(RuntimeError, 'HTTP 401 for .*/free page 1'):
            self.run_scrape(routes)

    def scrape_with(self, count, previous, previous_version='v5.0', models=None):
        models = models or [model(f'm{i}', 50) for i in range(count)]
        return self.run_scrape(paged(models, 200), scraper_aa.MIN_SCORED_MODELS, previous, previous_version,
                               scraper_aa.MIN_SCORED_NEW_INDEX)[0]

    def test_current_index_guard_uses_half_of_previous_on_same_version(self):
        with self.assertRaisesRegex(RuntimeError, 'below the floor of 352'):
            self.scrape_with(78, 704)
        with self.assertRaises(RuntimeError):
            self.scrape_with(351, 704)
        self.assertEqual(len(self.scrape_with(352, 704)), 352)

    def test_current_index_guard_skips_half_of_previous_after_version_change(self):
        floor = scraper_aa.MIN_SCORED_NEW_INDEX
        for version in [None, 'v4.3', 'v4']:
            with self.subTest(version=version):
                self.assertEqual(len(self.scrape_with(78, 704, version)), 78)
                with self.assertRaisesRegex(RuntimeError, f'below the floor of {floor}'):
                    self.scrape_with(floor - 1, 704, version)
        for previous in [None, 30]:
            with self.subTest(previous=previous), self.assertRaisesRegex(RuntimeError, f'below the floor of {floor}'):
                self.scrape_with(floor - 1, previous)
        self.assertEqual(len(self.scrape_with(floor, None)), floor)

    def v4_models(self, total, with_v4, v4_key='artificial_analysis_intelligence_index_v4_3'):
        models = [model(f'm{i}', 70 if i < 78 else None) for i in range(total)]
        for i, m in enumerate(models):
            m['evaluations'][v4_key] = 40.6 if i < with_v4 else None
        return models

    def test_v4_rule_used_when_v4_index_covers_enough_models(self):
        df = self.scrape_with(0, 704, None, self.v4_models(716, 400))
        self.assertEqual(len(df), 400)
        self.assertEqual(set(df['Intelligence Index']), {41})
        self.assertEqual(set(df.aa_version), {'v4.3'})
        for version in [None, 'v4.3', 'v5.0']:
            with self.subTest(version=version), self.assertRaisesRegex(RuntimeError, 'below the floor of 352'):
                self.scrape_with(0, 704, version, self.v4_models(716, 300))

    def test_v4_key_names_are_matched_defensively(self):
        cases = {'artificial_analysis_intelligence_index_v4': 'v4', 'artificial_analysis_intelligence_index_v4_0': 'v4.0',
                 'artificial_analysis_intelligence_index_v4.3': 'v4.3', 'aa_intelligence_index_V4': 'v4',
                 'intelligence_index_v_4_2': 'v4.2'}
        for key, label in cases.items():
            with self.subTest(key=key):
                rule = scraper_aa.choose_rule(self.v4_models(250, 250, key), 5)
                self.assertEqual((rule['name'], rule['key'], rule['label']), ('v4', key, label))
        for key in ['terminalbench_v4_0', 'artificial_analysis_coding_index_v4', 'artificial_analysis_intelligence_index_v40']:
            with self.subTest(key=key):
                self.assertEqual(scraper_aa.choose_rule(self.v4_models(250, 250, key), 5)['name'], 'current')

    def test_current_rule_used_when_v4_index_is_short_or_absent(self):
        for models, reason in [(self.v4_models(716, 150), 'has 150, below 200'), ([model(f'm{i}', 50) for i in range(300)], 'no v4')]:
            with self.subTest(reason=reason):
                rule = scraper_aa.choose_rule(models, 5)
                self.assertEqual((rule['name'], rule['key'], rule['label'], rule['floor']),
                                 ('current', scraper_aa.SCORE_KEY, 'v5.0', scraper_aa.MIN_SCORED_NEW_INDEX))
                self.assertIn(reason, rule['reason'])
        df = self.scrape_with(0, 704, 'v4.3', self.v4_models(716, 150))
        self.assertEqual((len(df), set(df.aa_version)), (78, {'v5.0'}))

    def test_logs_evaluation_keys_and_version_fields_without_scores(self):
        models = self.v4_models(5, 2)
        models[0]['evaluations']['artificial_analysis_coding_index'] = None
        models[0]['intelligence_index_version'] = 4.3
        models[1]['index_version'] = None
        with patch.object(scraper_aa, 'print_step') as log:
            rule = scraper_aa.choose_rule(models, 5)
        lines = [c.args[0] for c in log.call_args_list]
        self.assertEqual(lines[0], 'AA: evaluations keys with non-null counts over 5 models: '
                         'artificial_analysis_coding_index=0, artificial_analysis_intelligence_index=5, '
                         'artificial_analysis_intelligence_index_v4_3=2')
        self.assertEqual(lines[1], 'AA: top-level model fields that look like an index version: index_version=0, intelligence_index_version=1')
        self.assertNotIn('70', ' '.join(lines))
        self.assertEqual(rule['name'], 'current')

    def test_scrape_logs_rule_and_guard(self):
        with patch.object(scraper_aa, 'print_step') as log:
            self.scrape_with(78, 704, 'v4.3', [model(f'm{i}', 50) for i in range(78)])
        text = '\n'.join(c.args[0] for c in log.call_args_list)
        self.assertIn('AA: rule current uses artificial_analysis_intelligence_index as v5.0 because no v4 intelligence index key', text)
        self.assertIn('AA: size guard floor 50 (previous run was on index v4.3, half-of-previous skipped', text)

    def test_short_list_fails_before_scraped_file_is_written(self):
        update_src = (ROOT / 'update.py').read_text()
        self.assertLess(update_src.index('df = scrape();'), update_src.index('df.to_csv(out_file'))
        with patch.object(scraper_aa.pd.DataFrame, 'to_csv') as to_csv, self.assertRaises(RuntimeError):
            self.scrape_with(78, 704)
        to_csv.assert_not_called()

    def test_previous_run_reads_firebase_metadata(self):
        ref = Mock(); ref.get.return_value = {'rows_scraped': {'artificial_analysis': 704}, 'aa_index_version': 'v5.0'}
        fake_db = Mock(reference=Mock(return_value=ref))
        with patch.dict(scraper_aa.os.environ, {'FIREBASE_DATABASE_URL': 'https://example.invalid'}), \
                patch.dict('sys.modules', {'firebase_admin': Mock(db=fake_db), 'firebase_admin.db': fake_db}), \
                patch('scripts.firebase_upload._init_firebase') as init:
            self.assertEqual(scraper_aa.previous_run(), (704, 'v5.0'))
            init.assert_called_once_with('https://example.invalid')
            fake_db.reference.assert_called_once_with(scraper_aa.PREVIOUS_STATS_PATH)
            ref.get.return_value = {'rows_scraped': {'artificial_analysis': 704}}
            self.assertEqual(scraper_aa.previous_run(), (704, None))
            for bad in [None, True, '704', 0]:
                ref.get.return_value = {'rows_scraped': {'artificial_analysis': bad}, 'aa_index_version': 5}
                self.assertEqual(scraper_aa.previous_run(), (None, None))
            ref.get.return_value = 'stats'
            self.assertEqual(scraper_aa.previous_run(), (None, None))
            ref.get.side_effect = ValueError('down')
            self.assertEqual(scraper_aa.previous_run(), (None, None))
        with patch.dict(scraper_aa.os.environ, {'FIREBASE_DATABASE_URL': ''}):
            self.assertEqual(scraper_aa.previous_run(), (None, None))

    def test_metadata_records_aa_index_version(self):
        src = (ROOT / 'update.py').read_text()
        self.assertIn('"aa_index_version": str(aa_df["aa_version"].iloc[0])', src)
        self.assertLess(src.index('"rows_scraped": {'), src.index('"aa_index_version"'))

    def test_source_export_and_exact_variant_matching(self):
        funcs = pipeline_functions()
        df = parse([model()])
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

    def test_missing_aa_score_never_writes_or_blanks_history(self):
        funcs = pipeline_functions()
        header = 'date;model;lma;aa;lb;aa_estimated;aa_version;aa_slug\n'
        result = pd.DataFrame([dict(model='gpt54', lma=1477, aa=None, lb=77.97, aa_estimated=None, aa_version=None, aa_slug=None),
                               dict(model='new', lma=1400, aa=None, lb=None, aa_estimated=None, aa_version=None, aa_slug=None)])
        with tempfile.TemporaryDirectory() as tmp:
            history = Path(tmp) / 'history.csv'
            history.write_text(header + '2026-01-01;gpt54;1477;39;77.97;;v4.3;gpt-5-4\n')
            append = funcs['append_history']
            self.assertEqual(append(result, history), 1)
            self.assertEqual(append(result, history), 0)
            result.loc[0, 'lma'] = 1480
            self.assertEqual(append(result, history), 1)
            rows = pd.read_csv(history, sep=';')
            last = rows[rows.model == 'gpt54'].iloc[-1]
            self.assertEqual((last.lma, last.aa, last.lb, last.aa_version, last.aa_slug), (1480, 39, 77.97, 'v4.3', 'gpt-5-4'))
            history.write_text(header + '2026-01-01;gpt54;1477;39;77.97;;v4.3;gpt-5-4\n2026-10-29;gpt54;1477;;77.97;;;\n')
            result = result.iloc[:1].copy(); result.loc[0, 'lma'] = 1477
            self.assertEqual(append(result, history), 0)
            result.loc[0, 'lb'] = 78.1
            self.assertEqual(append(result, history), 1)
            last = pd.read_csv(history, sep=';').iloc[-1]
            self.assertEqual((last.aa, last.lb, last.aa_version), (39, 78.1, 'v4.3'))
            result.loc[0, ['aa', 'aa_version', 'aa_slug']] = [52, 'v5.0', 'gpt-5-4']
            self.assertEqual(append(result, history), 1)
            self.assertEqual(pd.read_csv(history, sep=';').iloc[-1].aa_version, 'v5.0')
            result.loc[0, 'lma'] = None
            self.assertEqual(append(result, history), 1)
            self.assertTrue(pd.isna(pd.read_csv(history, sep=';').iloc[-1].lma))

    def test_unknown_estimate_is_stable_and_untracked_check_uses_slug(self):
        funcs = pipeline_functions()
        result = pd.DataFrame([dict(model='gpt54', lma=1477, aa=39, lb=77.97,
                                    aa_estimated=None, aa_version='', aa_slug='gpt-5-4')])
        with tempfile.TemporaryDirectory() as tmp:
            history = Path(tmp) / 'history.csv'
            history.write_text('date;model;lma;aa;lb;aa_estimated;aa_version;aa_slug\n2026-01-01;gpt54;1477;39;77.97;0;v4.3;gpt-5-4\n')
            self.assertEqual(funcs['append_history'](result, history), 1)
            self.assertEqual(funcs['append_history'](result, history), 0)
        df = parse([model(), model('new-model', 50)])
        df['Model'] = ['GPT-5.4 (Xhigh)', 'New Model']
        tracking = pd.DataFrame([dict(model='gpt54', name='GPT 5.4', aa_lookup='GPT-5.4 (xhigh)', aa_slug='gpt-5-4')])
        untracked = funcs['get_untracked_models'](df, 'Artificial Analysis', ['index'], tracking, 'aa_slug', match_col='aa_slug')
        self.assertEqual([u['raw_name'] for u in untracked], ['New Model'])


if __name__ == '__main__':
    unittest.main()
