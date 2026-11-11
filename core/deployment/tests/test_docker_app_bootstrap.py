from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import _bootstrap  # noqa: F401

from lifecycle.docker.ops import compose_file_list
from docker_runtime import resolve_volume_binds
from render_common import render_docker_nginx_config
from lifecycle.context import DeploymentContext
from lifecycle.steps.docker_steps import DockerUpAppServicesStep


class DockerAppBootstrapTests(unittest.TestCase):
    def test_prod_bootstrap_starts_the_build_nginx_and_generated_workers(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            home = root / 'core/deployment/docker'
            home.mkdir(parents=True)
            (home / 'docker-compose.workers.generated.yml').write_text(
                'services:\n  celery-worker-demo: {}\n', encoding='utf-8',
            )
            context = DeploymentContext.create(root, docker_mode='prod', raw_env={
                'HOST_PROFILE': 'full', 'DOCKER_PROFILE_NGINX': 'true',
            })
            with patch('lifecycle.steps.docker_steps.docker_ops.build_compose_cmd', return_value=(['docker'], root)) as build, patch(
                'lifecycle.steps.docker_steps.subprocess.call', return_value=0,
            ):
                self.assertTrue(DockerUpAppServicesStep().run(context).ok)
            targets = build.call_args.kwargs['extra_args']
            self.assertIn('client-build', targets)
            self.assertNotIn('client', targets)
            self.assertIn('nginx', targets)
            self.assertIn('celery-worker-demo', targets)

    def test_prod_nginx_reads_the_client_build_volume(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            values = resolve_volume_binds(root, {'DOCKER_MODE': 'prod'})
            self.assertEqual(values['ERGO_CLIENT_DIST_BIND'], 'client_dist')
            values = resolve_volume_binds(root, {'DOCKER_MODE': 'dev'})
            self.assertEqual(Path(values['ERGO_CLIENT_DIST_BIND']), (root / 'core/client/dist').resolve())

    def test_docker_https_renders_tls_and_preserves_http_default(self):
        template = Path(__file__).resolve().parents[1] / 'docker/nginx/ergo_ms.docker.conf.template'
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'nginx.conf'
            render_docker_nginx_config(
                {'NGINX_LISTEN_PORT': '18443', 'NGINX_USE_HTTPS': 'true'},
                template_path=template, output_path=output,
            )
            text = output.read_text(encoding='utf-8')
            self.assertIn('listen 18443 ssl;', text)
            self.assertIn('ssl_certificate /etc/ergo/tls/cert.pem;', text)
            self.assertIn('ssl_certificate_key /etc/ergo/tls/key.pem;', text)
            self.assertNotIn('proxy_pass http://jupyter:', text)
            render_docker_nginx_config({}, template_path=template, output_path=output)
            text = output.read_text(encoding='utf-8')
            self.assertIn('listen 80;', text)
            self.assertNotIn('ssl_certificate', text)

    def test_tls_mount_overlay_is_selected_only_with_nginx(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            overlay = home / 'docker-compose.nginx-tls.generated.yml'
            overlay.write_text('services: {}\n', encoding='utf-8')
            self.assertIn(overlay, compose_file_list('prod', {'DOCKER_PROFILE_NGINX': 'true'}, docker_home=home))
            self.assertNotIn(overlay, compose_file_list('prod', {'DOCKER_PROFILE_NGINX': 'false'}, docker_home=home))
