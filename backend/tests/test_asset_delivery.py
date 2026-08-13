"""
Static-asset delivery guards.

Compression and cache policy live in configuration files that no other test
reads, so a regression there is invisible until a user waits for 340 kB of
JavaScript again. These assertions are deliberately about *configuration*, not
runtime behaviour: they run everywhere, including where Docker is unavailable.

Runtime verification of the same settings happens in the `performance`
workflow, which builds the frontend and enforces `performance-budget.json`.
"""

import json
import re
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_ROOT.parent
FRONTEND = REPO_ROOT / "frontend"

FRONTEND_NGINX = (FRONTEND / "nginx.conf").read_text(encoding="utf-8")
FRONTEND_DOCKERFILE = (FRONTEND / "Dockerfile").read_text(encoding="utf-8")
PACKAGE_JSON = json.loads((FRONTEND / "package.json").read_text(encoding="utf-8"))
APP_JSX = (FRONTEND / "src" / "App.jsx").read_text(encoding="utf-8")


class TestCompressionDelivery:
    """Brotli must actually be served, not merely intended."""

    def test_brotli_module_is_installed_in_the_runtime_image(self):
        assert "nginx-mod-http-brotli" in FRONTEND_DOCKERFILE

    def test_brotli_module_is_loaded_by_the_config(self):
        # Without the include, every brotli_* directive is an unknown
        # directive and nginx refuses to start.
        assert "include /etc/nginx/modules/*.conf;" in FRONTEND_NGINX

    def test_precompressed_siblings_are_preferred_over_runtime_compression(self):
        assert "brotli_static on;" in FRONTEND_NGINX
        assert "gzip_static on;" in FRONTEND_NGINX

    def test_runtime_compression_covers_clients_without_a_sibling(self):
        assert re.search(r"^\s*brotli on;", FRONTEND_NGINX, re.MULTILINE)
        assert re.search(r"^\s*gzip on;", FRONTEND_NGINX, re.MULTILINE)

    def test_build_emits_the_precompressed_siblings(self):
        assert "precompress" in PACKAGE_JSON["scripts"]["build"]

    def test_compressed_responses_vary_on_accept_encoding(self):
        # A CDN that ignored this would hand a brotli body to a client that
        # cannot decode it.
        assert "gzip_vary on;" in FRONTEND_NGINX
        assert "$sent_http_content_encoding" in FRONTEND_NGINX
        assert "add_header Vary $icap_vary;" in FRONTEND_NGINX


class TestCdnDelivery:
    """Hashed assets must be cacheable at an edge, and reachable from one."""

    def test_hashed_assets_are_immutable_and_long_lived(self):
        assert 'add_header Cache-Control "public, immutable";' in FRONTEND_NGINX
        assert "expires 1y;" in FRONTEND_NGINX

    def test_the_html_shell_is_never_cached(self):
        assert 'add_header Cache-Control "no-store";' in FRONTEND_NGINX

    def test_assets_are_fetchable_cross_origin(self):
        assert 'add_header Access-Control-Allow-Origin "*";' in FRONTEND_NGINX

    def test_asset_urls_can_be_pointed_at_a_cdn(self):
        assert "ARG PUBLIC_URL" in FRONTEND_DOCKERFILE
        compose = (REPO_ROOT / "docker-compose.yml").read_text(encoding="utf-8")
        assert "PUBLIC_URL: ${CDN_BASE_URL:-}" in compose

    def test_the_edge_csp_can_admit_the_same_cdn(self):
        # An asset host that the CSP forbids is a broken deployment, so the
        # two settings are wired to one variable.
        edge_dockerfile = (REPO_ROOT / "nginx" / "Dockerfile").read_text(encoding="utf-8")
        assert "ARG CDN_ORIGIN" in edge_dockerfile
        compose = (REPO_ROOT / "docker-compose.yml").read_text(encoding="utf-8")
        assert "CDN_ORIGIN: ${CDN_BASE_URL:-}" in compose


class TestCodeSplitting:
    """The initial download must not contain every page in the app."""

    #: Pages heavy enough that shipping them eagerly is a measurable regression.
    LAZY_PAGES = (
        "UserDashboard",
        "AdminDashboard",
        "WellnessCoachDashboard",
        "Analytics",
        "Reports",
        "AlarmManager",
        "PracticeChallenge",
        "Profile",
    )

    def test_heavy_pages_are_lazily_imported(self):
        for page in self.LAZY_PAGES:
            assert re.search(
                rf"const {page} = React\.lazy\(\(\) => import\('\./pages/{page}'\)\)",
                APP_JSX,
            ), f"{page} is not code-split"

    def test_no_page_is_statically_imported_except_the_landing_route(self):
        static_pages = set(re.findall(r"^import (\w+) from '\./pages/(\w+)'", APP_JSX, re.MULTILINE))
        assert {name for name, _ in static_pages} == {"Login"}

    def test_suspended_routes_have_a_fallback(self):
        assert "React.Suspense" in APP_JSX
        assert "PageFallback" in APP_JSX

    def test_a_budget_guards_the_bundle(self):
        budget = json.loads((FRONTEND / "performance-budget.json").read_text(encoding="utf-8"))
        assert budget["budgets"]["initialJsGzipKB"] <= 200
        assert budget["requireLazyChunks"] >= 8
        assert "check:bundle-size" in PACKAGE_JSON["scripts"]
