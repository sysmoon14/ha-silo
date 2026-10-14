# Silo for Home Assistant

A Home Assistant integration for the [Silo](https://github.com/Silo-Server/silo-server) self-hosted media server. It turns each Android TV running the native Silo app into a media player you can start playback on, browse your libraries from, and control.

## What it does

- **Start playback on a TV.** `silo.play` plays a movie or episode by its Silo content ID. Give it a series or season ID and Silo picks a random episode for you.
- **Shuffle a show.** `silo.shuffle` plays a random episode of a series or season.
- **Play from the start.** `from_start: true` clears the profile's resume point before playing. This also marks the item unwatched for that profile.
- **Skip if already playing.** `skip_if_playing: true` does nothing when that title, or any episode of that series or season, is already on.
- **Now playing.** Each linked TV shows what Silo is playing: title, series, season and episode, artwork and position. Pause, resume and stop work from Home Assistant.
- **Media browser and search.** Browse the profile's Silo home rows (Continue Watching, Favorites, Recommended, Recently Added and so on), your library collections, and Movies and TV down to seasons and episodes, or search by title. Play anything from there; playing a series or season shuffles it. Artwork is served through Home Assistant, so it also shows when you're away from home.
- **Messages and stop.** `silo.send_message` shows a message on screen and `silo.stop_playback` stops playback. Target a TV, or a profile's sensor to reach whatever that profile is watching on any device.

## Server device

The integration also adds a **Silo server** device, with the TV players grouped under it. With an admin API key it has:

- **A "watching" sensor for each profile:** `idle`, `playing` or `paused`, with the title, series and episode, device and progress as attributes. It covers every device, not just linked TVs.
- **Sensors:** active streams and transcodes (with who's watching what as attributes), movies, shows, episodes, library size, requests awaiting approval, running background tasks and the time of the last library scan. Titles and failed requests are there too but disabled by default.
- **Buttons:** scan all libraries, scan each library on its own, refresh metadata, and restart the server.
- **`silo.run_task`:** start any of Silo's background tasks by its key, such as `database_maintenance` or `sync_markers`.

Without an admin key the server device only shows what that key is allowed to read.

## How playback starts

Silo has no API for "play this on that device", so the integration opens the Silo app's `silo://play/<id>` deep link on the TV through the [Android TV](https://www.home-assistant.io/integrations/androidtv/) (ADB) integration. Each Silo TV is linked to an existing Android TV media player.

## Requirements

- Home Assistant 2025.9 or newer.
- The Android TV (ADB) integration set up for each TV.
- A Silo API key created by a server admin with **no scopes**. Admin access is needed for the now-playing state and the pause, resume and stop controls; playback and browsing work without it.

## Install

1. In HACS, open the menu and choose **Custom repositories**. Add `https://github.com/sysmoon14/ha-silo` with type **Integration**.
2. Download **Silo**, then restart Home Assistant.
3. Go to **Settings → Devices & services → Add integration → Silo**.
4. Enter the server URL (for example `http://10.22.2.2:8090`) and the API key, without the word `Bearer`.
5. Pick the profile to use for browsing, shuffling and resume points, and the Android TV players that run Silo.

The TV's IP address is read from its Android TV setup and used to match it to Silo's playback sessions. You can change it under the integration's **Configure** options if Silo sees the TV at a different address.

## Examples

Play a movie from the start:

```yaml
action: silo.play
target:
  entity_id: media_player.living_room_tv
data:
  content_id: movie-tmdb-862
  from_start: true
```

Bedtime warning, then stop whatever Rosa is watching anywhere:

```yaml
- action: silo.send_message
  target:
    entity_id: sensor.silo_server_rosa_watching
  data:
    title: Bedtime
    message: Five more minutes!
- delay: "00:05:00"
- action: silo.stop_playback
  target:
    entity_id: sensor.silo_server_rosa_watching
```

Run a Silo background task:

```yaml
action: silo.run_task
data:
  task_key: database_maintenance
```

Play a random Bluey episode unless one is already on:

```yaml
action: silo.shuffle
target:
  entity_id: media_player.living_room_tv
data:
  scope_id: series-tvdb-353546
  skip_if_playing: true
```

The standard `media_player.play_media` action works too, with a Silo content ID as `media_content_id`.

Both actions return what was played (`content_id`, `title`, and `skipped`), so a script can use the result with `response_variable`.

## Finding content IDs

Open the TV's Silo player in the media browser: hovering a movie or episode shows its ID. Silo IDs look like `movie-tmdb-862`, `series-tvdb-353546`, `season-tvdb-353546-2` and `episode-tvdb-353546-2-8`.

## Development

```bash
pip install pytest-homeassistant-custom-component
pytest
```
