export function mergeAlarmQueue(previous, incoming, dismissed, now, syncStartedAt = null) {
  const ids = new Set(incoming.map(alarm => alarm.alarm_id));
  const retained = syncStartedAt === null ? previous : previous.filter(alarm => ids.has(alarm.alarm_id) || alarm.localReceivedAt >= syncStartedAt);
  return [...new Map([...retained, ...incoming].filter(alarm =>
    !dismissed.has(alarm.alarm_id) && (!alarm.expires_at || Date.parse(alarm.expires_at) > now)
  ).map(alarm => [alarm.alarm_id, alarm])).values()].sort((a, b) => a.server_sequence - b.server_sequence);
}
