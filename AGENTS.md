# AGENTS.md

## Project goals

Maintain SpotPRIS2 as a lightweight Spotify-to-MPRIS bridge.

## Compatibility

Do not make changes that break:
- the `spotpris2` CLI
- DBus/MPRIS compatibility
- `playerctl`
- existing command-line arguments
- Spotify Connect playback controls

## Development

- Prefer small, focused changes over large refactors.
- Add tests for behavioral changes.
- Never commit credentials or OAuth tokens.
- Never log Spotify access tokens, refresh tokens, client secrets, or authorization codes.
- Run the test suite after code changes.
- Update README documentation when user-facing setup changes.

## Git

Do not commit, push, rebase, or modify remote branches unless explicitly requested.