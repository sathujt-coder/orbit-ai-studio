FROM node:22-bookworm-slim
WORKDIR /opt/orbit
COPY package.json package-lock.json ./
RUN npm ci --ignore-scripts --no-audit --no-fund
COPY check.cjs ./
ENTRYPOINT ["node", "/opt/orbit/check.cjs"]
