FROM node:20-slim

WORKDIR /app

COPY package.json ./
RUN npm install

COPY . .

EXPOSE 3000
# Phase 0 runs in dev mode for simplicity; switch to build+start for production images.
CMD ["npm", "run", "dev"]
