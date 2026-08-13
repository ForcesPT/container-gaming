# Dockerfile — package the prebuilt Linux Electron AppDir into a file-bundle
# image at /opt/dpadcloud/launcher. The container-gaming image COPYs this in:
#   COPY --from=forcespt/dpadcloud-launcher /opt/dpadcloud/launcher /opt/dpadcloud/launcher
# The container-gaming Ubuntu base provides the glibc / NSS / GTK / nss libs
# the Electron binary links against; this image only ships the AppDir files.
#
# Build AFTER scripts/build.sh has produced dist/linux-unpacked/:
#   docker build -t forcespt/dpadcloud-launcher:0.1.0 -t forcespt/dpadcloud-launcher:latest .
FROM scratch
COPY dist/linux-unpacked/ /opt/dpadcloud/launcher/
LABEL org.opencontainers.image.title="dpad-launcher" \
      org.opencontainers.image.version="0.1.2" \
      org.opencontainers.image.description="DpadPlay 10-foot store launcher (Linux Electron AppDir)" \
      org.opencontainers.image.source="container-gaming/launcher"