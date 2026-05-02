FROM node:24-alpine

WORKDIR /app

# .npmrc を package*.json と一緒に先にコピーする (legacy-peer-deps=true 等の
# 設定が npm ci で効くようにする)。
COPY package.json package-lock.json* .npmrc ./
RUN npm ci --legacy-peer-deps || npm install --legacy-peer-deps

COPY . .

ARG API_URL=http://localhost:8000
ENV API_URL=$API_URL

RUN npm run build

ENV NODE_ENV=production
ENV HOSTNAME=0.0.0.0
ENV PORT=3000

EXPOSE 3000

CMD ["npm", "run", "start", "--", "--port", "3000", "--hostname", "0.0.0.0"]
