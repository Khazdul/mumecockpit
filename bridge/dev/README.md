# bridge/dev — dev fixtures for offline pane preview

Run the comm pane against the bundled fixture to verify rendering without a
live game session:

    COMM_STATE_PATH=bridge/dev/comm.state.fixture \
    COMM_FILTERS_CONF=/tmp/comm_filters.fixture.conf \
    python3 bridge/panes/comm_pane.py

`COMM_STATE_PATH` overrides the live state file so the pane reads static fixture
data instead of polling `bridge/comm.state`. `COMM_FILTERS_CONF` points at `/tmp`
so toggling filters in the fixture run does not touch the real
`bridge/comm_filters.conf`.

`comm.state.fixture` covers all ten channels in both self and other forms, with
edge cases: apostrophe inside a quoted message (tales/Besor), ANSI bold around a
talker prefix with a trailing language suffix (says/Vit), a quoted channel with no
apostrophes for the verbatim fallback (prayers/Elrond), and an emotes row where
the text does not start with the talker name (emotes/Vainamoinen).
