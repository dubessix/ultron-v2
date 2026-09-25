// V2 Step 4 - apply the backend's widget decision to the screen state.
// The AI decides (show_widget or the tool it used); the UI only obeys.
export function applyWidgetAction(prev, structured) {
  if (!structured || typeof structured !== 'object') return prev;
  const { action, widget_id: id, refresh } = structured;
  if (action === 'close_all_widgets') {
    const next = {};
    Object.keys(prev).forEach(key => { next[key] = { ...prev[key], visible: false }; });
    return next;
  }
  if (!id || !(id in prev)) return prev;
  if (action === 'close_widget') {
    return { ...prev, [id]: { ...prev[id], visible: false } };
  }
  if (action === 'open_widget') {
    const current = prev[id] || {};
    const reload = refresh && current.visible;
    return {
      ...prev,
      [id]: { ...current, visible: true, refreshKey: reload ? (current.refreshKey || 0) + 1 : (current.refreshKey || 0) },
    };
  }
  return prev;
}
