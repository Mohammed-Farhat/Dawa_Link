# Builds the website and serves it the way S3 + CloudFront will (docs/12 §4.1):
# static files, unknown paths answered with index.html, and the same security headers.
ARG NODE_IMAGE=node:24-alpine
ARG NGINX_IMAGE=nginx:1.29-alpine

FROM ${NODE_IMAGE} AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
# The API's address is built into the website.
ARG VITE_API_URL
ENV VITE_API_URL=${VITE_API_URL}
RUN npm run build

FROM ${NGINX_IMAGE}
ARG VITE_API_URL
# nginx fills this into the Content-Security-Policy when the container starts.
ENV API_ORIGIN=${VITE_API_URL}
COPY nginx.conf.template /etc/nginx/templates/default.conf.template
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
