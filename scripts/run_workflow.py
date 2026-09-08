"""
run_workflow.py
Command line entry point: reads config.json and runs the AOI -> mosaic ->
raster templates pipeline.

The pipeline itself lives in workflow.py, shared with the ArcGIS Pro toolbox.

  python run_workflow.py
  python run_workflow.py --config=C:/jobs/flood_survey.json
"""

import os
import sys
import json

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

import workflow


def resolve_config_path(repo_root, argv):
    """Config path from the command line, else config.json beside the repo root.

    Allows keeping several job profiles side by side rather than editing one file.
    """
    for arg in argv[1:]:
        if arg.startswith('--config='):
            return arg.split('=', 1)[1]
        if not arg.startswith('-'):
            return arg
    return os.path.join(repo_root, 'config.json')


def main(argv=None):
    argv = sys.argv if argv is None else argv
    config_path = resolve_config_path(workflow.REPO_ROOT, argv)

    if not os.path.exists(config_path):
        print('ERROR: config file not found at %s' % config_path)
        return 1

    print('Config: %s' % config_path)

    try:
        with open(config_path, 'r', encoding='utf-8') as handle:
            config = json.load(handle)
    except (IOError, OSError, json.JSONDecodeError) as exc:
        print('ERROR: could not read %s: %s' % (config_path, exc))
        return 1

    reporter = workflow.Reporter()

    try:
        results = workflow.build_mosaics(config, reporter)
    except ValueError as exc:
        print('ERROR: %s' % exc)
        return 1

    return workflow.summarise(results, config['output_folder'], reporter)


if __name__ == '__main__':
    sys.exit(main())
