# Voice

Local speech-to-text and text-to-speech for Home Assistant's Assist pipeline.
**Whisper** (`wyoming-whisper`) turns an utterance into text; **Piper**
(`wyoming-piper`) reads the answer back out. Both speak the [Wyoming
protocol](https://github.com/OHF-Voice/wyoming) over plain TCP, so Home
Assistant treats them as just another stt/tts engine behind the assistant.

Cluster-internal only: no Ingress, no oauth2-proxy, no port anywhere. The
NetworkPolicy opens the two Wyoming ports to the `home-assistant` namespace
and nothing else; the pods may reach cluster DNS and the internet (first-boot
downloads), nothing more.

## Wiring it up in Home Assistant

1. **Settings → Devices & services → Add integration → Wyoming Protocol**,
   twice:
   - host `wyoming-whisper.voice.svc.cluster.local`, port `10300`
   - host `wyoming-piper.voice.svc.cluster.local`, port `10200`
2. **Settings → Voice assistants** → edit the Home Assistant assistant:
   - **Speech-to-text**: `faster-whisper` (the entity the first integration
     adds)
   - **Text-to-speech**: the Piper entity, and pick a voice - every catalog
     voice is selectable: high-fidelity English (`en_US-lessac-high` is the
     default), `da_DK-talesyntese-medium`, Russian `ru_RU-*` and more.
   - Conversation stays on OpenRouter.
3. Press the microphone in the Assist dialog (browser or companion app) and
   talk; typed chat is untouched.

## Things to know

- **First boot downloads are real.** Whisper fetches the `medium-int8` model
  (~750 MB) before it starts listening at all; Piper fetches its default
  voice (~110 MB) and downloads any other catalog voice the first time it is
  requested. Until the download finishes the pods are honestly unready, not
  broken - `kubectl -n voice logs deploy/wyoming-whisper` shows the progress.
- **The volumes are a cache, which is why they are not in the backup.**
  Models re-download themselves; nothing on them is an original. The shipped
  whisper add-on excludes its models from backups the same way
  (`backup_exclude`).
- **Changing the whisper model** means editing `args` in whisper.yaml
  (`small-int8` = lighter and faster, `large-v3` = a heavier step up again;
  `medium-int8` is the current default). Changing Piper's *default* voice
  means editing its `--voice` arg; the other voices need no change here at
  all.
- **Sizing**: idle ~0 CPU, ~1.5-2 GB RAM standing between the two (the
  medium whisper model is most of it), a few seconds of CPU burst per
  command. `kubectl -n voice top pods` after a week
  of real use - the manifest numbers are a starting point, not a measurement.
- **Name biasing, for later**: the whisper server can read the names of
  conversation-exposed entities over the HA websocket (`--hass-token`) and
  feed them to the model, fixing the "Ecobee → incubi" class of mishearing.
  Not wired up; if misheard entity names annoy, that is the follow-up.
- No health endpoints exist in these images; the k8s probes are TCP connects
  to the Wyoming port, which only accepts once the server is serving.

## Verify

    kubectl -n voice get pods,svc
    kubectl -n voice logs deploy/wyoming-whisper
    kubectl -n voice logs deploy/wyoming-piper

The real test is one spoken command through Assist.
