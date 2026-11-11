"""Unified model index CLI; provider installers retain ownership of weights."""

import argparse
from contextlib import redirect_stdout
import json
from pathlib import Path
import sys

DEPLOYMENT = Path(__file__).resolve().parents[1]
if str(DEPLOYMENT) not in sys.path:
    sys.path.insert(0, str(DEPLOYMENT))

from cli_locale import t  # noqa: E402
from console_tags import configure_stdio_utf8, format_console  # noqa: E402
from model_index import ModelIndexError, build_index, install_models, resolve_local_model, write_index  # noqa: E402
from runtime_requirements import RuntimeRequirementsError  # noqa: E402


def main(argv=None):
    configure_stdio_utf8()
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument('--root', type=Path, default=argparse.SUPPRESS)
    common.add_argument('--json', action='store_true', default=argparse.SUPPRESS)
    parser = argparse.ArgumentParser(parents=[common])
    sub = parser.add_subparsers(dest='command', required=True)
    for command in ('list', 'check', 'install', 'resolve'):
        child = sub.add_parser(command, parents=[common])
        if command in ('install', 'resolve'):
            child.add_argument('--provider', default='')
            child.add_argument('--model', default='')
        if command == 'install':
            child.add_argument('--include-optional', action='store_true')
        if command == 'resolve':
            child.add_argument('--allow-download', action='store_true')
    args = parser.parse_args(argv)
    args.json = getattr(args, 'json', False)
    try:
        root = getattr(args, 'root', DEPLOYMENT.parents[1]).resolve()
        if not (root / 'pyproject.toml').is_file():
            raise ModelIndexError(t('project_root_not_found'))
        if args.command == 'resolve' or (args.command == 'install' and args.model):
            if not args.provider or not args.model:
                raise ModelIndexError(t('model_index_identity_required'))
            with redirect_stdout(sys.stderr):
                result = resolve_local_model(root, args.provider, args.model,
                                             allow_download=args.command == 'install' or args.allow_download)
        else:
            if args.command == 'install' and args.provider:
                raise ModelIndexError(t('model_index_identity_required'))
            with redirect_stdout(sys.stderr):
                result = install_models(root, include_optional=args.include_optional) if args.command == 'install' else build_index(root)
            if args.command == 'check':
                write_index(root, result)
        missing = [row for row in result.get('models', []) if row['required'] and not row['ready']]
        if args.json:
            print(json.dumps(result, ensure_ascii=False))
        else:
            print(format_console('error' if missing else 'ok', t('model_index_status', missing=len(missing))))
            for row in result.get('models', [result]):
                print(f"{row['provider']}:{row['name']} ready={row['ready']} path={row['local_path'] or '-'}")
        return int(args.command in ('check', 'install') and bool(missing))
    except (ModelIndexError, RuntimeRequirementsError, OSError, ValueError) as exc:
        print(format_console('error', str(exc)), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
