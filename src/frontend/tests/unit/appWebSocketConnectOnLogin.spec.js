// @vitest-environment jsdom
/**
 * The header connection indicator read "Disconnected" after a client-side
 * login until a reload: App.vue only called `connect()` in its mount path when
 * a token already existed, and a form login never remounts App.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { nextTick } from 'vue'

const connect = vi.fn()
vi.mock('../../src/utils/websocket', () => ({
  useWebSocket: () => ({ connect, disconnect: vi.fn() }),
}))
vi.mock('../../src/components/HelpChatWidget.vue', () => ({ default: { template: '<div />' } }))
vi.mock('vue-router', () => ({ useRoute: () => ({ meta: {} }) }))

import App from '../../src/App.vue'
import { useAuthStore } from '../../src/stores/auth'

function mountApp() {
  return mount(App, {
    global: { stubs: { 'router-view': true, KeepAlive: true } },
  })
}

describe('App WebSocket connect', () => {
  beforeEach(() => {
    localStorage.clear()
    connect.mockClear()
    setActivePinia(createPinia())
    window.matchMedia = vi.fn().mockImplementation((q) => ({
      matches: false, media: q, addEventListener: vi.fn(), removeEventListener: vi.fn(),
    }))
  })

  it('connects once when logged out at boot and a login then authenticates', async () => {
    const wrapper = mountApp()
    await nextTick()
    expect(connect).not.toHaveBeenCalled()

    useAuthStore().isAuthenticated = true
    await nextTick()
    expect(connect).toHaveBeenCalledTimes(1)
    wrapper.unmount()
  })

  it('connects exactly once on boot with a stored token', async () => {
    localStorage.setItem('token', 'stored.jwt.token')
    const wrapper = mountApp()
    await nextTick()
    await nextTick()
    expect(connect).toHaveBeenCalledTimes(1)
    wrapper.unmount()
  })
})
