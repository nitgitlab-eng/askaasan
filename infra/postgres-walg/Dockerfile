# Postgres 16 (alpine, same as the main stack) + WAL-G, for the optional point-in-time-recovery overlay
# infra/docker-compose.pitr.yml.
#
# WAL-G's release binaries are glibc builds, and moving an existing alpine (musl) data directory to a glibc image
# changes text collation and can corrupt indexes. So WAL-G is built from source here and the base image stays
# postgres:16-alpine.
ARG WALG_VERSION=v3.0.9

FROM golang:1.25-alpine AS walg
ARG WALG_VERSION
RUN apk add --no-cache git
WORKDIR /src
RUN git clone --depth 1 --branch "${WALG_VERSION}" https://github.com/wal-g/wal-g.git . \
 && for i in 1 2 3; do go mod download && break; sleep 10; done
# WAL-G 3.x uses encoding/json/v2, which Go 1.25 ships behind GOEXPERIMENT=jsonv2.
RUN cd main/pg \
 && CGO_ENABLED=0 GOEXPERIMENT=jsonv2 go build -trimpath \
      -ldflags "-s -w -X github.com/wal-g/wal-g/cmd/pg.walgVersion=${WALG_VERSION}" -o /out/wal-g .

FROM postgres:16-alpine
COPY --from=walg /out/wal-g /usr/local/libexec/wal-g
COPY wal-g-wrapper.sh /usr/local/bin/wal-g
COPY walg-basebackup.sh /usr/local/bin/walg-basebackup.sh
RUN chmod 0755 /usr/local/libexec/wal-g /usr/local/bin/wal-g /usr/local/bin/walg-basebackup.sh && wal-g --version
