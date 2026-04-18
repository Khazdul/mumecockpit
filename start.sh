#!/bin/bash
cd "$(dirname "$0")"

# -----------------------------
# ARGUMENT PARSING
# -----------------------------
SHOW_DEV=0
SHOW_UI=1

for arg in "$@"; do
    case $arg in
        -d) SHOW_DEV=1 ;;
        -u) SHOW_UI=1 ;;
        -du|-ud) SHOW_DEV=1; SHOW_UI=1 ;;
    esac
done

echo "Starting MUME cockpit..."
[ $SHOW_UI  -eq 1 ] && echo "   UI pane:  ON"
[ $SHOW_DEV -eq 1 ] && echo "   Dev pane: ON"

# -----------------------------
# 1. INSTALL DEPENDENCIES
# -----------------------------
if ! command -v tmux >/dev/null 2>&1; then
    echo "📦 Installing tmux..."
    sudo apt update && sudo apt install -y tmux
fi

if ! command -v lua >/dev/null 2>&1; then
    echo "📦 Installing lua..."
    sudo apt update && sudo apt install -y lua5.4
fi

# -----------------------------
# 2. CREATE DIRS AND LOGS
# -----------------------------
mkdir -p bridge logs

chmod +x bridge/open_pane.sh

# Reset log files on each startup
touch logs/debug.log logs/ui.log
> logs/debug.log
> logs/ui.log

# -----------------------------
# 3. KILL OLD SESSION
# -----------------------------
tmux kill-session -t mume 2>/dev/null || true

# -----------------------------
# 4. CREATE SESSION
# -----------------------------
TERM_COLS=$(tput cols)
TERM_LINES=$(tput lines)

tmux new-session -d -s mume -x "$TERM_COLS" -y "$TERM_LINES" -n cockpit
tmux set-option -t mume status off
tmux set-option -t mume mouse on

# Pane borders — discrete dark grey
tmux set-option -t mume pane-border-status top
tmux set-option -t mume pane-border-format "#{?pane_title,#{pane_title},}"
tmux set-option -t mume pane-border-style "fg=colour238"
tmux set-option -t mume pane-active-border-style "fg=colour238"

# -----------------------------
# 5. BUILD LAYOUT BASED ON ARGUMENTS
# -----------------------------
LAYOUT_CONF="$HOME/MUME/bridge/layout.conf"
[ -f "$LAYOUT_CONF" ] || printf "ui_width=33\nwindow_cols=0\n" > "$LAYOUT_CONF"
grep -q "^window_cols=" "$LAYOUT_CONF" || echo "window_cols=0" >> "$LAYOUT_CONF"
source "$LAYOUT_CONF"
LEFT_WIDTH=$(( TERM_COLS - ui_width - 1 ))
sed -i "s/^window_cols=.*/window_cols=$TERM_COLS/" "$LAYOUT_CONF"

# Create panes using direct command form — avoids shell prompt appearing in pane
if [ $SHOW_UI -eq 1 ] && [ $SHOW_DEV -eq 1 ]; then
    tmux split-window -h -t mume:cockpit.0 "tail -f $HOME/MUME/logs/ui.log"
    tmux select-pane -t mume:cockpit.1 -T "ui"
    tmux split-window -v -t mume:cockpit.1 "tail -f $HOME/MUME/logs/debug.log"
    tmux select-pane -t mume:cockpit.2 -T "dev"
    tmux resize-pane -t mume:cockpit.0 -x "$LEFT_WIDTH"
elif [ $SHOW_UI -eq 1 ]; then
    tmux split-window -h -t mume:cockpit.0 "tail -f $HOME/MUME/logs/ui.log"
    tmux select-pane -t mume:cockpit.1 -T "ui"
    tmux resize-pane -t mume:cockpit.0 -x "$LEFT_WIDTH"
elif [ $SHOW_DEV -eq 1 ]; then
    tmux split-window -h -t mume:cockpit.0 "tail -f $HOME/MUME/logs/debug.log"
    tmux select-pane -t mume:cockpit.1 -T "dev"
    tmux resize-pane -t mume:cockpit.0 -x "$LEFT_WIDTH"
fi

# -----------------------------
# 5b. REGISTER LAYOUT HOOKS
# -----------------------------
tmux set-hook -t mume window-resized \
  "run-shell 'bash $HOME/MUME/bridge/on_window_resize.sh'"
tmux bind-key -n MouseDragEnd1Border \
  "run-shell 'bash $HOME/MUME/bridge/on_pane_resize.sh'"

# -----------------------------
# 6. START TT++
# -----------------------------
tmux send-keys -t mume:cockpit.0 \
    "cd $HOME/MUME && tt++ ttpp/main.tin" C-m
tmux select-pane -t mume:cockpit.0 -T "MUME"
sleep 0.2 && tmux select-pane -t mume:cockpit.0 -T "MUME" &

# -----------------------------
# 7. OPEN INPUT PANE
# -----------------------------
bash "$HOME/MUME/bridge/open_pane.sh" input

# -----------------------------
# 8. FOCUS INPUT PANE
# -----------------------------
INPUT_INDEX=$(tmux list-panes -t mume:cockpit \
    -F '#{pane_index} #{pane_title}' \
    | awk '/^[0-9]+ input$/{print $1}')
if [ -n "$INPUT_INDEX" ]; then
    tmux select-pane -t mume:cockpit.$INPUT_INDEX
else
    tmux select-pane -t mume:cockpit.0
fi

tmux attach -t mume