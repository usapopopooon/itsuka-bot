FROM node:24-alpine

WORKDIR /app

COPY package.json package-lock.json* ./
RUN npm ci || npm install

COPY . .

ARG API_URL=http://localhost:8000
ENV API_URL=$API_URL

RUN npm run build

ENV NODE_ENV=production
ENV HOSTNAME=0.0.0.0
ENV PORT=3000

EXPOSE 3000

CMD ["npm", "run", "start", "--", "--port", "3000", "--hostname", "0.0.0.0"]
