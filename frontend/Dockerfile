# Builds the website and serves it the way S3 + CloudFront will (docs/12 §4.1):
# static files, unknown paths answered with index.html, and the same security headers.
ARG NODE_IMAGE=node:24-alpine
ARG NGINX_IMAGE=nginx:1.29-alpine

FROM ${NODE_IMAGE} AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
# The API's address is built into the website, for good. Without it every call would go
# to the website's own address and come back as a page (A#17): stop here, with the reason.
# (vite.config.ts checks the address itself too.) Declared after `npm ci`, so that a new
# address doesn't download the packages again.
ARG VITE_API_URL
RUN test -n "$VITE_API_URL" || { echo "VITE_API_URL is not set: build with --build-arg VITE_API_URL=<the API's address> (docs/12 §12)." >&2; exit 1; }
ENV VITE_API_URL=${VITE_API_URL}
RUN npm run build

FROM ${NGINX_IMAGE}
ARG VITE_API_URL
# nginx fills this into the Content-Security-Policy when the container starts.
ENV API_ORIGIN=${VITE_API_URL}
COPY nginx.conf.template /etc/nginx/templates/default.conf.template
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
