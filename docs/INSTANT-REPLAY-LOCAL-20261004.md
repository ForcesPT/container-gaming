# Selected Epic replay candidate

October 4, 2026. Local only; no image publication or paid VM.

Instant's launcher publishes an allowlisted desktop environment into a 0600 file
inside its private `/run/user/<uid>` directory. It contains operational display,
audio and controller settings, excludes account variables/URIs, and is discarded
with the session container. Replay refuses symlinks, shared/oversized files,
unknown fields, other runtime paths and root execution.

The host supplies no store URI. The replay helper loads this environment and the
wrapper rederives the selected catalog request from the sealed release. It rejects
a running/unknown selected game. A private replay lock prevents concurrent request
wrappers. An existing managed official Epic receives its second-instance request;
a closed client follows the ordinary Instant startup. Store entitlement and cloud
conflicts stay within official Epic.

Seventeen offline non-root Linux cases pass: four private environment tests, five
real shell/lock wrapper tests and eight observation tests including a real /proc
process double. The companion host controller separately journals exact-owner
delivery before mutation and never repeats an ambiguous command.

`Dockerfile.instant-replay` builds an account-free local derivative. Both maintained
Epic Instant Dockerfiles package the helper. GE-Proton11-7 is unchanged. This does
not establish actual official-client replay, restored saves, cloud-sync completion
or native GPU/WebRTC acceptance; worker/API image allowlists remain disabled.

The exact local image `sha256:3442ee78246481519e58e916fb776c6a992971b345d76f5d751b8a025b51e495`
was built from `c856ed3` over the verified local observation image. Its five
packaged helper hashes match source; all 17 offline cases pass against those
packaged bytes. The first attempt incorrectly mounted fixture process doubles
on a noexec temporary directory; the corrected executable fixture passed.
Receipt: `qualification/instant-replay-image-local-20261004.json`.
