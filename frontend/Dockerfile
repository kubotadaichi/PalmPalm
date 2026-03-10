FROM node:20-alpine

WORKDIR /app

# 依存関係を先にコピーしてキャッシュを効かせる
COPY package*.json ./
RUN npm install

# ソースは volumes でマウントするので COPY しない
EXPOSE 5173

CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0"]
