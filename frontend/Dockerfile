# syntax=docker/dockerfile:1

# ---------- Stage 1: Angular Production Build ----------
FROM node:20-alpine AS build

WORKDIR /app

# Abhängigkeiten separat kopieren/installieren, damit dieser (teure) Layer
# nur bei Änderungen an package*.json neu gebaut wird.
COPY package.json package-lock.json ./
RUN npm ci

COPY . .
RUN npm run build

# ---------- Stage 2: Auslieferung via Nginx ----------
FROM nginx:alpine

COPY nginx.conf /etc/nginx/conf.d/default.conf

# Angulars neuer "application"-Builder legt den Browser-Output unter
# dist/frontend/browser ab (siehe angular.json -> outputPath).
COPY --from=build /app/dist/frontend/browser /usr/share/nginx/html

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
