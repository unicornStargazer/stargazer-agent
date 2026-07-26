import { mount } from '@vue/test-utils';
import { describe, expect, it } from 'vitest';

import AgentProfileMenu from './AgentProfileMenu.vue';

describe('AgentProfileMenu', () => {
  it('closes the error popover before requesting a retry', async () => {
    const wrapper = mount(AgentProfileMenu, {
      props: {
        profiles: [],
        selectedProfileId: 'default',
        state: 'error',
        error: 'Profile service unavailable',
        disabled: false,
      },
    });

    await wrapper.get('.profile-trigger').trigger('click');
    expect(wrapper.find('.profile-popover').exists()).toBe(true);

    await wrapper.get('.profile-error button').trigger('click');

    expect(wrapper.emitted('retry')).toHaveLength(1);
    expect(wrapper.find('.profile-popover').exists()).toBe(false);
  });

  it('does not open a menu for a single ready Profile', async () => {
    const wrapper = mount(AgentProfileMenu, {
      props: {
        profiles: [{ id: 'default', name: '默认助手', model: 'test-model' }],
        selectedProfileId: 'default',
        state: 'ready',
        error: undefined,
        disabled: false,
      },
    });

    expect(wrapper.get('.profile-trigger').attributes('aria-haspopup')).toBeUndefined();
    await wrapper.get('.profile-trigger').trigger('click');
    expect(wrapper.find('.profile-popover').exists()).toBe(false);
  });
});
