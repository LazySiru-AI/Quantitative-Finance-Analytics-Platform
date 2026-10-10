# syntax=docker/dockerfile:1.7
# ---------------------------------------------------------------------------
# Frontend image: Vite/React app compiled to static assets, served by nginx.
#
# Build context is the repo root (see docker-compose.yml). This image never
# touches the repo-root `data/` directory or `.env` -- the frontend has no
# business with either, and .dockerignore excludes both from the build
# context regardless.
#
# Multi-stage: `npm run dev` is never run in the container. Stage 1 compiles
# with Node; stage 2 is nginx serving the compiled `dist/` output only -- the
# Node toolchain, node_modules and source never reach the shipped image.
#
# nginx also reverse-proxies /api/ to a backend, so the browser only ever
# talks to one origin (this container). That sidesteps backend/app/main.py's
# CORS allow-list entirely (it only lists the Vite *dev-server* origins,
# http://localhost:5173 etc.) -- the backend only ever receives same-origin
# requests through this proxy, so CORS headers are irrelevant rather than
# misconfigured. That stays true regardless of where the backend runs.
#
# Where the proxy points is a *runtime* choice, not baked in at build time --
# see the ENV API_PROXY_TARGET / NGINX_ENVSUBST_FILTER comment below. Two
# topologies share this one image:
#   - Default (docker-compose.yml, no profile): backend runs on the Windows
#     host (repo venv, host Anthropic credentials); API_PROXY_TARGET defaults
#     to http://host.docker.internal:8000.
#   - `docker compose --profile backend up`: the old both-in-Docker topology,
#     API_PROXY_TARGET overridden to http://backend:8000 (the Compose service
#     name/network). See docker-compose.yml and docs/DOCKER.md.
# ---------------------------------------------------------------------------

# Pinned by digest, not just tag: a tag (even a specific patch tag like `20.17.0-alpine`) can be
# re-pushed to point at different bytes; a digest cannot. Digest resolved via
# `curl -s "https://auth.docker.io/token?service=registry.docker.io&scope=repository:library/node:pull"`
# then a HEAD-equivalent GET for the `docker-content-digest` response header on
# `https://registry-1.docker.io/v2/library/node/manifests/20.17.0-alpine` (multi-arch index digest --
# the same one `docker pull node:20.17.0-alpine` would resolve to). Re-resolve with
# `docker buildx imagetools inspect node:20.17.0-alpine` if this ever needs to move.
FROM node:20.17.0-alpine@sha256:2d07db07a2df6830718ae2a47db6fedce6745f5bcd174c398f2acdda90a11c03 AS build

WORKDIR /build

# Install from the lockfile before copying source, so dependency install is
# cached independently of source edits.
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci

COPY frontend/index.html frontend/vite.config.ts frontend/tsconfig.json ./
COPY frontend/src ./src

RUN npm run build

# ---------------------------------------------------------------------------
# Pinned by digest, not just tag -- same reasoning as the `node` base above. Digest resolved the
# same way against `https://registry-1.docker.io/v2/library/nginx/manifests/1.27.1-alpine`.
# Re-resolve with `docker buildx imagetools inspect nginx:1.27.1-alpine` if this ever needs to move.
FROM nginx:1.27.1-alpine@sha256:a5127daff3d6f4606be3100a252419bfa84fd6ee5cd74d0feaca1a5068f97dcf AS runtime

# Listen on an unprivileged port so the whole process (not just workers) can
# run as the non-root `nginx` user already present in this base image --
# ports below 1024 need root to bind, so we deliberately avoid :80.
#
# The config below is written as an nginx *template*
# (/etc/nginx/templates/default.conf.template), not a static conf.d file.
# The official nginx image's own docker-entrypoint.d/20-envsubst-on-templates.sh
# runs `envsubst` over every file under /etc/nginx/templates/ each time the
# container starts (normal `nginx` CMD path only -- see docs/DOCKER.md) and
# writes the result to /etc/nginx/conf.d/<name>.conf (the `.template` suffix
# stripped). That makes the proxy target below resolved at *container start*
# from the API_PROXY_TARGET environment variable, not fixed at image build
# time -- required so the same image can proxy to a host backend or to the
# `backend` Compose service without a rebuild (see docker-compose.yml).
#
# envsubst has no "substitute only this variable" mode by default -- called
# with no explicit variable list it replaces every `$name`/`${name}` it
# finds, which would also eat nginx's *own* runtime variables used below
# ($host, $remote_addr, $proxy_add_x_forwarded_for, $scheme) since none of
# those names exist in this container's environment -- each would silently
# become an empty string. NGINX_ENVSUBST_FILTER (read by that same
# entrypoint script) restricts substitution to environment variable names
# matching the given regex, so only API_PROXY_TARGET is touched and nginx's
# own `$...` variables pass through the template untouched. Verified by
# actually rendering the template against a running container -- see
# docs/DOCKER.md -- the rendered /etc/nginx/conf.d/default.conf contains a
# resolved proxy_pass target *and* a literal, unsubstituted `$host` etc.
ENV API_PROXY_TARGET=http://host.docker.internal:8000
ENV NGINX_ENVSUBST_FILTER=^API_PROXY_TARGET$

RUN <<'NGINX_CONF'
mkdir -p /etc/nginx/templates
cat > /etc/nginx/templates/default.conf.template <<'CONF'
server {
    listen 8080;
    server_name _;

    root /usr/share/nginx/html;
    index index.html;

    # -------------------------------------------------------------------
    # Security headers (defence in depth, not a fix for a known hole).
    #
    # An independent audit of this frontend found zero DOM-injection sinks:
    # no dangerouslySetInnerHTML, innerHTML, outerHTML, document.write,
    # eval or new Function anywhere in frontend/src, confirmed against the
    # built bundle too. There is no markdown renderer and nothing here
    # parses untrusted HTML. So there is nothing for a CSP to be *fixing*
    # today -- these headers exist to contain a future regression (a
    # dependency bump that adds one of those sinks, a careless copy-paste),
    # not to patch a live issue. They cost nothing to add because the app
    # is already strictly same-origin: nginx proxies /api/ itself (see
    # below), the Vite build emits no inline <script>, no external fonts,
    # images or stylesheets, and every frontend/src/api/*.ts call uses a
    # relative path.
    #
    # add_header only applies to responses nginx generates or serves
    # directly (the SPA's static files and 404s), which is everything this
    # container returns on non-/api/ paths -- proxied /api/ responses carry
    # the backend's own headers instead, as they should.
    #
    #   default-src 'self'   Fallback for every fetch directive not listed
    #                        explicitly below; keeps this same-origin by
    #                        default rather than by enumeration.
    #   script-src 'self'    No 'unsafe-inline' or 'unsafe-eval': the build
    #                        emits only `<script type="module" src=...>`
    #                        tags (see index.html / the built dist/), never
    #                        an inline <script> block, and grep across
    #                        frontend/src found no eval/new Function. If a
    #                        future dependency needs inline script, that
    #                        should be a deliberate, reviewed loosening of
    #                        this line, not a silent break someone works
    #                        around by deleting the header.
    #   style-src 'self' 'unsafe-inline'
    #                        React sets a handful of dynamic inline styles
    #                        as DOM `style="..."` attributes (chart heights
    #                        in components/Chart.tsx, the Fear & Greed
    #                        meter marker position in
    #                        components/FearGreedGauge.tsx, swatch colours
    #                        in components/IndicatorPicker.tsx). CSP has no
    #                        nonce/hash mechanism for style *attributes*
    #                        (only for <style> elements and stylesheet
    #                        links), so 'unsafe-inline' is the only way to
    #                        allow those without rewriting the app to push
    #                        every dynamic value through CSS custom
    #                        properties instead. This only permits inline
    #                        *styles*, not script, so it does not weaken
    #                        script-src.
    #   img-src 'self'       No images are loaded from anywhere but this
    #                        origin's own build output (no <img>, no
    #                        background-image url(), no data: URIs found).
    #   font-src 'self'      All fonts are OS/system stacks declared in
    #                        styles.css (ui-monospace, ui-sans-serif, etc.)
    #                        -- no @font-face, no Google Fonts or other CDN.
    #   connect-src 'self'   Every frontend/src/api/*.ts fetch() call uses a
    #                        relative path (e.g. `/api/health`), proxied by
    #                        the location block below -- the browser never
    #                        talks to any other origin.
    #   object-src 'none'    No <object>/<embed>/plugins anywhere in the
    #                        app; closes off a legacy Flash/plugin-based
    #                        injection vector some browsers still honour.
    #   base-uri 'self'      Stops an injected <base> tag from silently
    #                        rewriting where every relative URL (including
    #                        the API calls above) resolves to.
    #   form-action 'self'   The app's <form> elements (symbol entry, rule
    #                        editor, backtest controls, etc.) are all
    #                        handled by onSubmit + fetch, never a native
    #                        cross-origin submission -- this just makes
    #                        that the enforced ceiling too.
    #   frame-ancestors 'none'
    #                        Refuses to render inside a frame on *any*
    #                        origin, including this one -- the modern,
    #                        CSP-native equivalent of X-Frame-Options DENY
    #                        below (kept together deliberately; see that
    #                        header's own comment for why both are set).
    # Checked against the built bundle (`npm run build`, 2026-08-12), which is
    # ground truth in a way that reading `src/` is not:
    #   - `dist/index.html` carries exactly one script tag and it has a `src`.
    #     No inline script anywhere, so `script-src 'self'` -- with no
    #     'unsafe-inline' and no 'unsafe-eval' -- does not break the app.
    #   - The built CSS contains no `url(...)` at all and no `data:` URI, so
    #     `img-src 'self'` and `font-src 'self'` have nothing to block.
    #   - Four external origins appear as *strings* in the bundle and none is
    #     a subresource load: w3.org is an SVG xmlns, react.dev/reactrouter.com
    #     are error-message links, apache.org is a licence header.
    #     `http://localhost` is React Router's internal base for URL parsing,
    #     not a request. tradingview.com is `createElement("a").href` -- the
    #     attribution link, i.e. navigation, which CSP fetch directives do not
    #     govern.
    # Still unverified: that nginx actually emits these headers on a live
    # response, and that no CSP violation appears in a real browser console.
    # Both need Docker, which was not available when this was written.
    add_header Content-Security-Policy "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self'; font-src 'self'; connect-src 'self'; object-src 'none'; base-uri 'self'; form-action 'self'; frame-ancestors 'none'" always;

    # Stops a browser from ever re-sniffing a response's declared
    # Content-Type (e.g. treating a .js file requested as something else,
    # or a user-controlled upload, as executable/HTML). Nothing here relies
    # on sniffing, so this only removes an attack surface.
    add_header X-Content-Type-Options "nosniff" always;

    # Belt-and-braces alongside the CSP's frame-ancestors 'none' above:
    # frame-ancestors is the modern mechanism and already covers this, but
    # X-Frame-Options is understood by a couple of older/embedded user
    # agents that predate CSP frame-ancestors support, so both are set
    # rather than relying on CSP alone.
    add_header X-Frame-Options "DENY" always;

    # This app renders a user's real portfolio, tax figures and (via
    # pages/Ticker.tsx et al.) ticker symbols in the URL query string on
    # some views. `no-referrer` means none of that ever leaks in a Referer
    # header to a third party the page happens to link or fetch from --
    # simplest and strictest option, and there is no cross-site referrer
    # this app depends on for anything to function.
    add_header Referrer-Policy "no-referrer" always;

    # Deliberately NOT setting Strict-Transport-Security here: this is
    # served over plain HTTP on 127.0.0.1 (see docker-compose.yml), and
    # HSTS is a browser-wide, host-keyed policy -- sending it for
    # `localhost`/`127.0.0.1` would poison the browser's HSTS cache for
    # that host across every other project on this machine that happens to
    # use the same loopback address on plain HTTP, breaking them instead of
    # securing this one. Add HSTS only if this is ever served over TLS on
    # its own real hostname.
    # -------------------------------------------------------------------

    # Reverse-proxy API calls to whichever backend API_PROXY_TARGET names at
    # container start (see the ENV/NGINX_ENVSUBST_FILTER comment above --
    # default http://host.docker.internal:8000, overridden to
    # http://backend:8000 under `docker compose --profile backend up`). The
    # frontend code calls relative paths like `/api/health` (see
    # frontend/src/api/client.ts) so no build-time API base URL is needed --
    # this proxy is the only wiring required to reach either backend.
    location /api/ {
        proxy_pass ${API_PROXY_TARGET}/api/;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    # Client-side routing (react-router-dom): unknown paths fall back to
    # index.html rather than a bare nginx 404.
    location / {
        try_files $uri $uri/ /index.html;
    }
}
CONF
NGINX_CONF

COPY --from=build /build/dist /usr/share/nginx/html

# Run the master process itself as non-root, not just the workers: drop the
# `user` directive (meaningless -- and a startup warning -- once nothing runs
# as root to begin with), move the pid file somewhere the `nginx` user can
# write, and hand ownership of the paths nginx writes to at runtime to that
# user.
RUN sed -i '/^user  *nginx;/d; s#/var/run/nginx.pid#/tmp/nginx.pid#' /etc/nginx/nginx.conf \
    && touch /tmp/nginx.pid \
    && chown -R nginx:nginx /usr/share/nginx/html /var/cache/nginx /tmp/nginx.pid /etc/nginx/conf.d

USER nginx

EXPOSE 8080

CMD ["nginx", "-g", "daemon off;"]
