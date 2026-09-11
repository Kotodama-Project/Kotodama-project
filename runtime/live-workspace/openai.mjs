/** Official OpenAI Live protocol; no Realtime-API compatibility guesswork. */
import { check, LiveWorkspaceError, mediaSession } from './core.mjs';

/**
 * SDK classes are supplied by the host, allowing its existing hash-locked
 * dependency graph to own OpenAI + ws. No API key is accepted from a channel.
 * The returned connector is inert until ChannelWorkspaceHub calls start().
 */
export function openAILiveConnector({ OpenAI, LiveWS, apiKey }) {
  check(typeof OpenAI === 'function' && typeof LiveWS === 'function', 'live_sdk_required');
  check(typeof apiKey === 'string' && apiKey.length > 0, 'server_credential_required');
  const client = new OpenAI({ apiKey, baseURL: 'https://api.openai.com/v1', maxRetries: 0,
    timeout: 15000, logLevel: 'off' });
  return async () => {
    let socket = null; let eventHandler; let closeHandler; let closed = false;
    return {
      onEvent(handler) { check(!socket && typeof handler === 'function', 'listener_order'); eventHandler = handler; },
      onClose(handler) { check(!socket && typeof handler === 'function', 'listener_order'); closeHandler = handler; },
      start(event) {
        check(!socket && !closed && eventHandler && closeHandler, 'listener_order');
        try {
          // Reconnection is deliberately disabled: replay requires owner reconciliation.
          socket = new LiveWS(client, { reconnect: null, maxQueueSize: 65536,
            maxPayload: 131072, handshakeTimeout: 15000, perMessageDeflate: false });
          socket.on('error', () => { eventHandler({ type: 'error' }); });
          socket.on('event', value => eventHandler(value));
          socket.on('close', () => { closed = true; closeHandler(); });
          socket.send(event); // SDK queues only the startup event until WS opens.
        } catch { this.close(); throw new LiveWorkspaceError('live_connect_failed'); }
      },
      send(event) {
        check(socket && !closed, 'transport_unavailable');
        const pending = socket.socket?.platformSocket?.bufferedAmount;
        check(Number.isFinite(pending), 'live_sdk_incompatible');
        check(pending + Buffer.byteLength(JSON.stringify(event)) <= 65536, 'transport_backpressure');
        socket.send(event);
      },
      close() {
        if (closed) return; closed = true;
        try { socket?.close({ code: 1000, reason: 'Kotodama session ended' }); } catch { /* no raw error output */ }
      },
    };
  };
}

/** Server-side WebRTC signaling. Caller must perform authentication, consent,
 * rate limits, scope/ACL checks and sideband attachment before exposing this.
 * Does not register a public HTTP route or send provider credentials to a browser.
 */
export async function createWebRTCSession({ client, offer, signal }) {
  check(typeof client?.live?.create === 'function', 'live_sdk_required');
  check(typeof offer === 'string' && offer.startsWith('v=0')
    && Buffer.byteLength(offer) <= 65536, 'invalid_sdp');
  try {
    const response = await client.live.create({ session: mediaSession(),
      transport: { type: 'webrtc', sdp: offer } }, { signal, timeout: 15000, maxRetries: 0 });
    check(response?.transport?.type === 'webrtc' && typeof response.transport.sdp === 'string'
      && Buffer.byteLength(response.transport.sdp) <= 65536
      && typeof response.session?.id === 'string' && response.session.id.length <= 256,
    'invalid_live_response');
    return Object.freeze({ sessionId: response.session.id, answer: response.transport.sdp });
  } catch (error) {
    if (error instanceof LiveWorkspaceError) throw error;
    throw new LiveWorkspaceError('live_signaling_failed');
  }
}
