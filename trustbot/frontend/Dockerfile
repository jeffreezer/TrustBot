FROM node:20-slim

WORKDIR /app

COPY package.json ./
RUN npm install

COPY . .

# NEXT_PUBLIC_* is inlined into the client bundle at BUILD time, so the API URL the
# browser calls must be known here — passed as a build arg (deploy.sh sets it to the
# deployed API URL; docker-compose sets it to http://localhost:8000). Production build.
ARG NEXT_PUBLIC_API_URL=http://localhost:8000
ENV NEXT_PUBLIC_API_URL=${NEXT_PUBLIC_API_URL}
RUN npm run build

EXPOSE 3000
# `next start` honors $PORT (Cloud Run sets it); defaults to 3000 locally. See package.json.
CMD ["npm", "run", "start"]
