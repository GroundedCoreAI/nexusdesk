import { h } from 'vue'
import DefaultTheme from 'vitepress/theme'

import EditOnGithub from './EditOnGithub.vue'
import './custom.css'

export default {
  extends: DefaultTheme,
  Layout() {
    return h(DefaultTheme.Layout, null, {
      // Replaces the built-in edit link so the English locale can point at the
      // `*.en.md` source file instead of the Chinese one.
      'doc-footer-before': () => h(EditOnGithub),
    })
  },
}
