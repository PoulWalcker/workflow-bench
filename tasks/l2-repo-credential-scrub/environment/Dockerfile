FROM workflow-bench-agents:codex-0.162.1

RUN apt-get update \
    && apt-get install -y --no-install-recommends git=1:2.47.3-0+deb13u1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
RUN git config --global user.email "test@example.com" \
    && git config --global user.name "Test User" \
    && GIT_TERMINAL_PROMPT=0 git -c credential.helper= clone --quiet \
        https://github.com/jeffreywpli/test-secret-removal.git dclm \
    && test "$(git -C dclm rev-parse HEAD)" = "8df3c81f7a9c8df2fb2ed417ff7d6afdfec2492e"

WORKDIR /app/dclm
