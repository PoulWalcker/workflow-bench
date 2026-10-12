// One bounded, model-free UI decision step. All locators come from fresh trees.
function step(state, response) {
  const s = structuredClone(state);
  function done(status, reason_code = null) {
    return {...s, done: true, claim: {status, reason_code, result: null}};
  }
  function request(phase, operation, args = {}) {
    return {...s, phase, operation, arguments: args, done: false};
  }
  if (response?.error) return done('unknown', response.error.code);
  const o = response?.result;
  function nodes(n) { return [n, ...(n.children || []).flatMap(nodes)]; }
  function observe(phase) { return request(phase, 'ui_observe'); }
  function action(node, phase, kind = 'activate', text) {
    if (!node) return done('unknown', 'target_unavailable');
    return request(phase, 'ui_action', {action: kind,
      locator: {scope: o.scope, revision: o.revision, ref: node.ref},
      ...(text === undefined ? {} : {text})});
  }
  function control(label, kind) {
    return nodes(o.tree).find(n => n.simulation?.label === label && n.simulation.actions.includes(kind));
  }
  function contacts() {
    return nodes(o.tree).filter(n => n.simulation?.identity?.display_name === s.input.display_name && n.simulation.actions.includes('activate'));
  }
  // Every action is followed by a new observation, including focus changes.
  if (s.phase?.startsWith('after:')) return observe(s.phase.slice(6));
  if (!s.phase) return observe('start');
  if (!o?.tree || o.coverage.tree !== 'complete' || !o.coverage.collection.complete)
    return done('unknown', 'observation_incomplete');
  if (s.phase === 'start') {
    s.index = 0; s.matches = [];
    if (o.screen !== 'chat_list') return action(control('Back', 'activate'), 'after:list');
    s.phase = 'list';
  }
  if (s.phase === 'list') {
    const rows = contacts();
    if (s.index < rows.length) return action(rows[s.index], 'after:history');
    if (s.matches.length !== 1) return done('refused', s.matches.length ? 'ambiguous_recipient' : 'not_found');
    return action(rows[s.matches[0]], 'after:target');
  }
  if (s.phase === 'history') {
    const matches = nodes(o.tree).some(n => n.simulation?.direction === 'incoming' && n.simulation.value.includes(s.input.reference));
    if (matches) s.matches.push(s.index);
    s.index += 1;
    return action(control('Back', 'activate'), 'after:list');
  }
  if (s.phase === 'target') return action(control('Message', 'focus'), 'after:focused', 'focus');
  if (s.phase === 'focused') return action(control('Message', 'replace_text'), 'after:ready', 'replace_text', s.input.text);
  if (s.phase === 'ready') {
    s.oldEqual = nodes(o.tree).filter(n => n.simulation?.direction === 'outgoing' && n.simulation.value === s.input.text).length;
    return action(control('Send', 'activate'), 'after:sent');
  }
  if (s.phase === 'sent') {
    const equal = nodes(o.tree).filter(n => n.simulation?.direction === 'outgoing' && n.simulation.value === s.input.text).length;
    return equal === s.oldEqual + 1 ? done('completed') : done('unknown', 'effect_unknown');
  }
  return done('unknown', 'invalid_phase');
}
