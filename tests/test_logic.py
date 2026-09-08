"""
test_logic.py
Covers the parts of the workflow that do not need an ArcGIS licence: the exit
code decision, scene selection modes, template pack resolution, and config
back-compatibility. arcpy is stubbed so the real modules still import.

Run with the ArcGIS Pro Python (it needs pystac-client for the live STAC checks):
  "C:/Program Files/ArcGIS/Pro/bin/Python/envs/arcgispro-py3/python.exe" tests/test_logic.py
"""

import ast
import os
import sys
import types

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(REPO, 'scripts')
sys.path.insert(0, SCRIPTS)

# Stub arcpy: nothing under test calls it, but the modules import it at load time.
_stub = types.ModuleType('arcpy')
_stub.da = types.ModuleType('arcpy.da')
_stub.management = types.ModuleType('arcpy.management')
sys.modules.setdefault('arcpy', _stub)
sys.modules.setdefault('arcpy.da', _stub.da)

failures = []


def check(label, got, want):
    ok = got == want
    print('  %-58s %s' % (label, 'ok' if ok else 'FAIL got=%r want=%r' % (got, want)))
    if not ok:
        failures.append(label)


def load_functions(path, names, extra_globals=None):
    """Execute selected top-level functions from a module that needs a licence."""
    tree = ast.parse(open(path, encoding='utf-8').read())
    picked = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in names]
    namespace = dict(extra_globals or {})
    namespace.setdefault('os', os)
    namespace.setdefault('print', print)
    exec(compile(ast.Module(body=picked, type_ignores=[]), path, 'exec'), namespace)
    return namespace


def test_exit_code():
    print('=== MDCS.run_failed (exit code decision) ===')
    run_failed = load_functions(os.path.join(SCRIPTS, 'MDCS.py'), {'run_failed'})['run_failed']

    check('False (could not start) -> failed', run_failed(False), True)
    check('None -> failed', run_failed(None), True)
    check('[] (nothing ran) -> failed', run_failed([]), True)
    check('all commands True -> success',
          run_failed([{'cmd': 'CM', 'value': True}, {'cmd': 'AR', 'value': True}]), False)
    check('one command False -> failed',
          run_failed([{'cmd': 'CM', 'value': True}, {'cmd': 'AR', 'value': False}]), True)
    check("dict status 'false' -> failed",
          run_failed([{'cmd': 'AR', 'value': {'status': 'false'}}]), True)
    check('dict status True -> success',
          run_failed([{'cmd': 'AR', 'value': {'status': True}}]), False)
    check('dict without status -> not a failure',
          run_failed([{'cmd': 'AR', 'value': {'other': 1}}]), False)


class _SilentLog(object):
    const_general_text = 0

    def Message(self, message, level=0):
        pass


class _FakeItem(object):
    def __init__(self, item_id, grid, cloud=1, when='2026-06-01T00:00:00Z'):
        self.id = item_id
        self.properties = {'grid:code': grid, 'eo:cloud_cover': cloud, 'datetime': when}


def test_scene_selection():
    print('\n=== scene selection modes ===')
    import MDCS_UC

    uc = MDCS_UC.UserCode()
    data = {'log': _SilentLog()}

    # Two tiles x three days, with a clear winner on 06-02 (both tiles, low cloud).
    items = [
        _FakeItem('a1', 'MGRS-38QNM', 40, '2026-06-01T07:00:00Z'),
        _FakeItem('a2', 'MGRS-38QNM', 5, '2026-06-02T07:00:00Z'),
        _FakeItem('a3', 'MGRS-38QNN', 8, '2026-06-02T07:00:00Z'),
        _FakeItem('a4', 'MGRS-38QNN', 2, '2026-06-03T07:00:00Z'),
    ]

    check('tileKey prefers grid:code', uc.tileKey(items[0]), 'MGRS-38QNM')
    check('tileKey falls back to id when grid:code is absent',
          uc.tileKey(types.SimpleNamespace(id='S2A_33UUP_20240601_0_L2A', properties={})),
          '33UUP')

    check('all keeps every scene', len(uc.selectScenes(data, items, 'all')), 4)

    per_tile = uc.selectScenes(data, items, 'best_scene_only')
    check('best_scene_only -> one per tile', len(per_tile), 2)
    check('best_scene_only picks lowest cloud',
          sorted(i.id for i in per_tile), ['a2', 'a4'])
    check('best_scene_only draws from whatever dates are best',
          len({i.properties['datetime'][:10] for i in per_tile}), 2)

    # Date must not influence the choice at all: the clearest scene wins even
    # when it is the oldest one available for that tile.
    oldest_is_clearest = [
        _FakeItem('old_clear', 'MGRS-38QNM', 1, '2026-06-01T07:00:00Z'),
        _FakeItem('new_cloudy', 'MGRS-38QNM', 55, '2026-06-30T07:00:00Z'),
    ]
    picked = uc.selectScenes(data, oldest_is_clearest, 'best_scene_only')
    check('oldest scene wins when it is the clearest',
          [i.id for i in picked], ['old_clear'])

    # Date only breaks ties between equally clear scenes.
    same_cloud = [
        _FakeItem('older_tie', 'MGRS-38QNM', 7, '2026-06-01T07:00:00Z'),
        _FakeItem('newer_tie', 'MGRS-38QNM', 7, '2026-06-30T07:00:00Z'),
    ]
    check('equal cloud cover breaks the tie on the newer scene',
          [i.id for i in uc.selectScenes(data, same_cloud, 'best_scene_only')], ['newer_tie'])

    coherent = uc.selectScenes(data, items, 'date_coherent')
    check('date_coherent -> single day',
          {i.properties['datetime'][:10] for i in coherent}, {'2026-06-02'})
    check('date_coherent keeps widest coverage', len(coherent), 2)

    # The old id.split('_')[1] key mapped every Landsat scene to 'L2SP'.
    landsat = [_FakeItem('LC09_L2SP_165044_20260903_02_T1', 'WRS2-165044'),
               _FakeItem('LC09_L2SP_166045_20260903_02_T1', 'WRS2-166045')]
    check('Landsat ids keep distinct tiles',
          len({uc.tileKey(i) for i in landsat}), 2)

    check('empty input is handled', uc.selectScenes(data, [], 'best_scene_only'), [])


def mosaic_band_count():
    """Band count the workflow config declares, so the check follows the config."""
    from xml.dom import minidom
    config = os.path.join(REPO, 'Parameter', 'Config', 'mosaic_workflow.xml')
    return int(minidom.parse(config).getElementsByTagName('num_bands')[0].firstChild.data)


def test_templates():
    print('\n=== template packs ===')
    import templates as T

    directory = os.path.join(REPO, 'Parameter', 'RasterFunctionTemplates')
    every, _ = T.resolve_templates(['all'], directory)

    check('every resolved template exists on disk',
          [t for t in every if not os.path.exists(os.path.join(directory, t))], [])

    water, _ = T.resolve_templates(['water'], directory)
    check('a pack is a subset of all', set(water).issubset(set(every)), True)

    overlapping, _ = T.resolve_templates(['fire', 'geology'], directory)
    check('overlapping packs de-duplicate', len(overlapping), len(set(overlapping)))

    unknown, warnings = T.resolve_templates(['nope'], directory)
    check('unknown pack warns and falls back', bool(warnings) and bool(unknown), True)

    empty, _ = T.resolve_templates([], directory)
    check('empty selection defaults to all', len(empty), len(every))

    # Every template that can be attached must be a well-formed raster function
    # template, or Pro fails when the user picks it from the dropdown.
    from xml.dom import minidom
    malformed = []
    for name in every:
        try:
            document = minidom.parse(os.path.join(directory, name))
            if document.documentElement.tagName != 'RasterFunctionTemplate':
                malformed.append(name)
            elif not document.getElementsByTagName('Function'):
                malformed.append(name)
        except Exception:
            malformed.append(name)
    check('every resolvable template is a valid RasterFunctionTemplate', malformed, [])

    # No attachable template may reference a band the mosaic does not have.
    # ExtractBand uses 0-based ids (max 11); band arithmetic expressions use
    # 1-based band numbers (max 12). Getting this wrong renders a flat image
    # rather than raising, so it is easy to ship unnoticed.
    import re
    band_count = mosaic_band_count()
    offenders = []
    import glob
    on_disk = sorted(os.path.basename(p) for p in glob.glob(os.path.join(directory, '*.rft.xml')))
    check('every template on disk is attachable', sorted(every), on_disk)
    for name in on_disk:
        text = open(os.path.join(directory, name), encoding='utf-8').read()
        for match in re.finditer(
                r'<Name>BandIDs[^<]*</Name>.{0,400}?'
                r'<Value xsi:type=.typens:ArrayOfInt.>(.*?)</Value>', text, re.S):
            for value in re.findall(r'<Int>(\d+)</Int>', match.group(1)):
                if int(value) > band_count - 1:
                    offenders.append('%s: ExtractBand id %s' % (name, value))
        for expression in re.findall(r'<Value xsi:type=.xs:string.>([^<]*B\d[^<]*)</Value>', text):
            for value in re.findall(r'\bB(\d{1,2})\b', expression):
                if int(value) > band_count:
                    offenders.append('%s: expression band B%s' % (name, value))
    check('no attachable template reads past band %d' % band_count, offenders, [])



def test_config():
    print('\n=== config back-compatibility ===')
    class _Reporter(object):
        def warning(self, text):
            print('  (%s)' % text)

    # resolve_scene_selection lives in the shared pipeline module; the config
    # path helper belongs to the command line runner.
    selection = load_functions(
        os.path.join(SCRIPTS, 'workflow.py'),
        {'resolve_scene_selection'},
        {'VALID_SELECTION': ('all', 'best_scene_only', 'date_coherent'),
         'Reporter': _Reporter})['resolve_scene_selection']
    config_path = load_functions(
        os.path.join(SCRIPTS, 'run_workflow.py'),
        {'resolve_config_path'})['resolve_config_path']

    check('legacy best_scene_only=true', selection({'best_scene_only': True}), 'best_scene_only')
    check('legacy best_scene_only=false', selection({'best_scene_only': False}), 'all')
    check('explicit scene_selection wins',
          selection({'best_scene_only': True, 'scene_selection': 'date_coherent'}),
          'date_coherent')
    check('invalid scene_selection falls back', selection({'scene_selection': 'nope'}), 'all')

    check('--config= honoured', config_path('/repo', ['x', '--config=/tmp/a.json']), '/tmp/a.json')
    check('positional config honoured', config_path('/repo', ['x', '/tmp/b.json']), '/tmp/b.json')
    check('default config path', config_path('/repo', ['x']),
          os.path.join('/repo', 'config.json'))


def main():
    test_exit_code()
    test_scene_selection()
    test_templates()
    test_config()

    print('\n%s' % ('-' * 60))
    print('FAILURES: %s' % (failures if failures else 'none'))
    return 1 if failures else 0


if __name__ == '__main__':
    sys.exit(main())
