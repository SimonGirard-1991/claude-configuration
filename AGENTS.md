# Pointer to the maintainer notes

Claude Code reads this file in any session under the home directory whose project has no
`CLAUDE.md` of its own (`~/.claude/CLAUDE.md` does not count, so `~/.claude` sessions read it
too). Before a change that `git -C ~/.claude status` would show, editing a file or adding one,
read `~/.claude/MAINTAINERS.md`: the agents' roles, the reviewer memory protocol and the dated
decision log. Writing memory, plans or transcripts under `~/.claude` does not count. Keep this
file to this pointer, since every line here costs those sessions.
