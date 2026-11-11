# Caddy con el módulo de DNS de Cloudflare: así saca el certificado HTTPS aunque el servidor
# esté en la red del local y no reciba conexiones de internet (modo red-local).
FROM caddy:2.10-builder AS compilador
RUN xcaddy build --with github.com/caddy-dns/cloudflare

FROM caddy:2.10
COPY --from=compilador /usr/bin/caddy /usr/bin/caddy
