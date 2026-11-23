# Build-time downloads are restricted to a controlled CI build step.
# The resulting immutable local image ID is used with --pull never at runtime.
FROM node:22-bookworm-slim
RUN npm install --global --ignore-scripts --no-audit --no-fund \
    typescript@5.9.3 tsx@4.20.6 \
    && tsc --version && tsx --version
