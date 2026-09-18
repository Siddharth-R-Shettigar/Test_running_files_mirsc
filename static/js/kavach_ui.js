/**
 * KAVACH — UI Framework Core
 * Handles:
 *  - Theme (Dark / Light) with visual UI preview cards
 *  - Dynamic Accent Color Chooser (Purple, Blue, Teal, Ruby, Amber)
 *  - Operational Modes with floating context menu
 *  - Fullscreen Dual-Pane Settings Modal
 */
(function () {
  'use strict';

  // ── 1. ACCENT COLOR PALETTES ──────────────────────────────────────
  const ACCENT_KEY = 'kavach-accent-color';
  const ACCENT_PALETTES = {
    purple: {
      name: 'DigiLocker Purple',
      main: '#4527a0',
      deep: '#1a237e',
      amber: '#7c4dff',
      peach: '#9575cd',
      subtle: '#ede7f6',
      grad: 'linear-gradient(135deg, #7c4dff 0%, #4527a0 50%, #1a237e 100%)'
    },
    blue: {
      name: 'Cyber Blue',
      main: '#1d4ed8',
      deep: '#0f172a',
      amber: '#2563eb',
      peach: '#60a5fa',
      subtle: '#eff6ff',
      grad: 'linear-gradient(135deg, #3b82f6 0%, #1d4ed8 50%, #0f172a 100%)'
    },
    teal: {
      name: 'Emerald Teal',
      main: '#0f766e',
      deep: '#134e4a',
      amber: '#0d9488',
      peach: '#5eead4',
      subtle: '#f0fdfa',
      grad: 'linear-gradient(135deg, #14b8a6 0%, #0f766e 50%, #134e4a 100%)'
    },
    ruby: {
      name: 'Crimson Ruby',
      main: '#be123c',
      deep: '#881337',
      amber: '#e11d48',
      peach: '#fda4af',
      subtle: '#fff1f2',
      grad: 'linear-gradient(135deg, #f43f5e 0%, #be123c 50%, #881337 100%)'
    },
    amber: {
      name: 'Warm Amber',
      main: '#b45309',
      deep: '#78350f',
      amber: '#d97706',
      peach: '#fde68a',
      subtle: '#fffbeb',
      grad: 'linear-gradient(135deg, #f59e0b 0%, #b45309 50%, #78350f 100%)'
    }
  };

  window.setAccentColor = function (accentId) {
    const palette = ACCENT_PALETTES[accentId] || ACCENT_PALETTES.purple;
    const root = document.documentElement;
    root.style.setProperty('--brand-orange', palette.main);
    root.style.setProperty('--brand-orange-deep', palette.deep);
    root.style.setProperty('--brand-orange-amber', palette.amber);
    root.style.setProperty('--brand-orange-peach', palette.peach);
    root.style.setProperty('--brand-orange-subtle', palette.subtle);
    root.style.setProperty('--grad-primary', palette.grad);
    root.style.setProperty('--orbit-color', palette.amber);
    root.style.setProperty('--orbit-glow', palette.peach);

    localStorage.setItem(ACCENT_KEY, accentId);

    // Update active state in UI swatches
    document.querySelectorAll('.accent-swatch').forEach(sw => {
      if (sw.getAttribute('data-accent') === accentId) {
        sw.classList.add('active');
      } else {
        sw.classList.remove('active');
      }
    });

    // Update label text
    document.querySelectorAll('.active-accent-name').forEach(el => {
      el.textContent = palette.name;
    });
  };

  // Initialize accent on load
  const savedAccent = localStorage.getItem(ACCENT_KEY) || 'purple';
  window.setAccentColor(savedAccent);

  // ── 2. THEME MANAGEMENT (DARK / LIGHT WITH VISUAL CARDS) ──────────
  const THEME_KEY = 'kavach-theme';
  const savedTheme = localStorage.getItem(THEME_KEY) || 'light';
  document.documentElement.setAttribute('data-theme', savedTheme);

  window.toggleTheme = function (isDark) {
    const theme = isDark ? 'dark' : 'light';
    document.documentElement.setAttribute('data-theme', theme);
    localStorage.setItem(THEME_KEY, theme);

    // Sync theme preview cards
    document.querySelectorAll('.theme-card-option').forEach(card => {
      const cardTheme = card.getAttribute('data-theme-val');
      if (cardTheme === theme) {
        card.classList.add('active');
      } else {
        card.classList.remove('active');
      }
    });

    // Sync any legacy switch inputs
    document.querySelectorAll('.theme-toggle-input').forEach(input => {
      input.checked = isDark;
    });
  };

  // ── 3. OPERATIONAL LOCATION / MODE MANAGEMENT ─────────────────────
  const LOC_KEY = 'kavach-operational-location';
  const defaultLoc = 'Airport Mode (T3)';

  function updateLocationDisplay(locName) {
    document.querySelectorAll('.loc-display-text').forEach(el => {
      el.textContent = locName;
    });

    // Update context menu items
    document.querySelectorAll('.mode-menu-item').forEach(btn => {
      const mode = btn.getAttribute('data-location') || btn.getAttribute('data-mode');
      if (mode === locName) {
        btn.classList.add('active');
      } else {
        btn.classList.remove('active');
      }
    });

    // Update modal options
    document.querySelectorAll('.modal-mode-option').forEach(btn => {
      const mode = btn.getAttribute('data-location') || btn.getAttribute('data-mode');
      if (mode === locName) {
        btn.classList.add('active');
      } else {
        btn.classList.remove('active');
      }
    });

    document.querySelectorAll('.loc-option-btn').forEach(btn => {
      if (btn.getAttribute('data-location') === locName) {
        btn.classList.add('active');
      } else {
        btn.classList.remove('active');
      }
    });
  }

  window.setLocation = function (locName) {
    localStorage.setItem(LOC_KEY, locName);
    updateLocationDisplay(locName);
    // Close context menu if open
    document.querySelectorAll('.mode-dropdown-wrapper').forEach(w => w.classList.remove('open'));
  };

  // ── 4. MODE CONTEXT MENU DROPDOWN ─────────────────────────────────
  window.toggleModeMenu = function (e) {
    if (e) e.stopPropagation();
    const wrapper = document.querySelector('.mode-dropdown-wrapper');
    if (wrapper) {
      wrapper.classList.toggle('open');
    }
  };

  window.closeModeMenu = function () {
    const wrapper = document.querySelector('.mode-dropdown-wrapper');
    if (wrapper) {
      wrapper.classList.remove('open');
    }
  };

  // ── 5. FULLSCREEN DUAL-PANE SETTINGS MODAL ────────────────────────
  function ensureSettingsModalInDOM() {
    let modal = document.getElementById('settingsModal');
    if (!modal) {
      modal = document.createElement('div');
      modal.id = 'settingsModal';
      modal.className = 'kavach-modal-backdrop';
      modal.setAttribute('aria-hidden', 'true');
      modal.innerHTML = `
        <div class="kavach-modal-card settings-dual-pane-modal" role="dialog" aria-modal="true" aria-labelledby="settingsModalTitle">
          
          <!-- Top Bar with Brand & Close -->
          <div class="settings-modal-topbar">
            <div class="settings-modal-brand">
              <img src="/static/img/logo_transparent.png" class="brand-logo-img" alt="Kavach">
              <div>
                <span class="settings-modal-title" id="settingsModalTitle">Terminal Configuration</span>
                <span class="settings-modal-sub">KAVACH Forensic Kiosk Engine · Node #408</span>
              </div>
            </div>
            <button type="button" class="modal-close-btn" onclick="closeSettingsModal()" aria-label="Close settings">
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2"><path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12"/></svg>
            </button>
          </div>

          <!-- Dual Pane Body -->
          <div class="settings-split-body">
            
            <!-- LEFT PANE: Headings Navigation -->
            <nav class="settings-nav-sidebar" aria-label="Settings Categories">
              <button type="button" class="settings-nav-tab active" data-tab="appearance">
                <svg class="nav-tab-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M7 21a4 4 0 01-4-4V5a2 2 0 012-2h4a2 2 0 012 2v12a4 4 0 01-4 4zm0 0h12a2 2 0 002-2v-4a2 2 0 00-2-2h-2.343M11 7.343l1.657-1.657a2 2 0 012.828 0l2.829 2.829a2 2 0 010 2.828l-8.486 8.485M7 17h.01"/></svg>
                <span>Appearance</span>
              </button>

              <button type="button" class="settings-nav-tab" data-tab="mode">
                <svg class="nav-tab-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M3.055 11H5a2 2 0 012 2v1a2 2 0 002 2 2 2 0 012 2v2.945M8 3.935V5.5A2.5 2.5 0 0010.5 8h.5a2 2 0 012 2 2 2 0 104 0 2 2 0 012-2h1.064M15 20.488V18a2 2 0 012-2h3.064M21 12a9 9 0 11-18 0 9 9 0 0118 0z"/></svg>
                <span>Operational Mode</span>
              </button>

              <button type="button" class="settings-nav-tab" data-tab="account">
                <svg class="nav-tab-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z"/></svg>
                <span>Officer Account</span>
              </button>

              <button type="button" class="settings-nav-tab" data-tab="about">
                <svg class="nav-tab-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"/></svg>
                <span>About KAVACH</span>
              </button>

              <div class="settings-sidebar-bottom">
                <a href="/logout" class="btn-sidebar-logout" title="End Session">
                  <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2"><path stroke-linecap="round" stroke-linejoin="round" d="M17 16l4-4m0 0l-4-4m4 4H7m6 4v1a3 3 0 01-3 3H6a3 3 0 01-3-3V7a3 3 0 013-3h4a3 3 0 013 3v1"/></svg>
                  <span>Terminate Session</span>
                </a>
              </div>
            </nav>

            <!-- RIGHT PANE: Selected Category Settings -->
            <div class="settings-content-pane">

              <!-- TAB 1: APPEARANCE -->
              <div class="settings-tab-panel active" id="tab-appearance">
                <h3 class="pane-heading">Appearance &amp; Theme</h3>
                <p class="pane-sub">Choose UI color mode, accent color highlights, and animation motion.</p>

                <!-- Visual Theme Selection Cards -->
                <div class="theme-picker-grid">
                  <button type="button" class="theme-card-option" data-theme-val="light">
                    <div class="theme-card-preview preview-light">
                      <div class="mockup-header"></div>
                      <div class="mockup-body">
                        <div class="mockup-line" style="width: 70%;"></div>
                        <div class="mockup-box"></div>
                      </div>
                    </div>
                    <div class="theme-card-meta">
                      <span class="theme-card-title">Light Theme</span>
                      <span class="theme-card-check">✓</span>
                    </div>
                  </button>

                  <button type="button" class="theme-card-option" data-theme-val="dark">
                    <div class="theme-card-preview preview-dark">
                      <div class="mockup-header"></div>
                      <div class="mockup-body">
                        <div class="mockup-line" style="width: 70%;"></div>
                        <div class="mockup-box"></div>
                      </div>
                    </div>
                    <div class="theme-card-meta">
                      <span class="theme-card-title">Dark Theme</span>
                      <span class="theme-card-check">✓</span>
                    </div>
                  </button>
                </div>

                <!-- Accent Color Picker -->
                <div class="accent-section">
                  <div class="accent-label">
                    <span>Accent Highlight Color</span>
                    <span class="active-accent-name">DigiLocker Purple</span>
                  </div>
                  <div class="accent-swatches-row">
                    <button type="button" class="accent-swatch" data-accent="purple" title="DigiLocker Purple" style="--swatch-color: #7c4dff; --swatch-deep: #4527a0;"></button>
                    <button type="button" class="accent-swatch" data-accent="blue" title="Cyber Blue" style="--swatch-color: #2563eb; --swatch-deep: #1d4ed8;"></button>
                    <button type="button" class="accent-swatch" data-accent="teal" title="Emerald Teal" style="--swatch-color: #0d9488; --swatch-deep: #0f766e;"></button>
                    <button type="button" class="accent-swatch" data-accent="ruby" title="Crimson Ruby" style="--swatch-color: #e11d48; --swatch-deep: #be123c;"></button>
                    <button type="button" class="accent-swatch" data-accent="amber" title="Warm Amber" style="--swatch-color: #d97706; --swatch-deep: #b45309;"></button>
                  </div>
                </div>

                <!-- Motion Toggle -->
                <div class="modal-toggle-row">
                  <div>
                    <h4>Reduced Motion</h4>
                    <p>Disable continuous revolving ambient glow &amp; spring animations.</p>
                  </div>
                  <label class="switch" aria-label="Toggle reduced motion">
                    <input type="checkbox" class="motion-toggle-input">
                    <span class="slider"></span>
                  </label>
                </div>
              </div>

              <!-- TAB 2: OPERATIONAL MODE -->
              <div class="settings-tab-panel" id="tab-mode">
                <h3 class="pane-heading">Operational Deployment Post</h3>
                <p class="pane-sub">Select the active deployment profile for this kiosk.</p>

                <div class="mode-modal-grid">
                  <button type="button" class="modal-mode-option active" data-location="Airport Mode (T3)">
                    <div class="mode-option-left">
                      <svg class="mode-opt-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M3.055 11H5a2 2 0 012 2v1a2 2 0 002 2 2 2 0 012 2v2.945M8 3.935V5.5A2.5 2.5 0 0010.5 8h.5a2 2 0 012 2 2 2 0 104 0 2 2 0 012-2h1.064M15 20.488V18a2 2 0 012-2h3.064M21 12a9 9 0 11-18 0 9 9 0 0118 0z"/></svg>
                      <div>
                        <span class="mode-opt-title">Airport Mode</span>
                        <span class="mode-opt-sub">Terminal 3 International Kiosk</span>
                      </div>
                    </div>
                    <span class="mode-opt-radio"></span>
                  </button>

                  <button type="button" class="modal-mode-option" data-location="Border Checkpoint Alpha">
                    <div class="mode-option-left">
                      <svg class="mode-opt-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M9 12l2 2 4-4m5.618-4.016A11.955 11.955 0 0112 2.944a11.955 11.955 0 01-8.618 3.04A12.02 12.02 0 003 9c0 5.591 3.824 10.29 9 11.622 5.176-1.332 9-6.03 9-11.622 0-1.042-.133-2.052-.382-3.016z"/></svg>
                      <div>
                        <span class="mode-opt-title">Border Checkpoint</span>
                        <span class="mode-opt-sub">Land Border Control Alpha</span>
                      </div>
                    </div>
                    <span class="mode-opt-radio"></span>
                  </button>

                  <button type="button" class="modal-mode-option" data-location="Customs Inspection Desk">
                    <div class="mode-option-left">
                      <svg class="mode-opt-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2m-3 7h3m-3 4h3m-6-4h.01M9 16h.01"/></svg>
                      <div>
                        <span class="mode-opt-title">Customs Desk</span>
                        <span class="mode-opt-sub">Secondary Inspection Area</span>
                      </div>
                    </div>
                    <span class="mode-opt-radio"></span>
                  </button>
                </div>
              </div>

              <!-- TAB 3: ACCOUNT -->
              <div class="settings-tab-panel" id="tab-account">
                <h3 class="pane-heading">Officer Account &amp; Station Identity</h3>
                <p class="pane-sub">Session credentials and cryptographic authorization parameters.</p>

                <div class="modal-account-card">
                  <div class="modal-account-avatar">O</div>
                  <div class="modal-account-info">
                    <div class="modal-account-name">officer@agency.gov.in</div>
                    <div class="modal-account-badge">Level 3 Forensic Examiner · Station Node #408</div>
                  </div>
                </div>

                <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 12px; margin-top: 16px;">
                  <div style="padding: 14px; border-radius: 14px; background: var(--surface-input); border: 1px solid var(--border-subtle);">
                    <span style="font-size: 11.5px; color: var(--text-muted); display: block;">Session Level</span>
                    <strong style="font-size: 14px; color: var(--text-main);">Level 3 Biometric Gate</strong>
                  </div>
                  <div style="padding: 14px; border-radius: 14px; background: var(--surface-input); border: 1px solid var(--border-subtle);">
                    <span style="font-size: 11.5px; color: var(--text-muted); display: block;">Pipeline Mode</span>
                    <strong style="font-size: 14px; color: var(--text-main);">Sub-second Edge Fast-UI</strong>
                  </div>
                </div>
              </div>

              <!-- TAB 4: ABOUT -->
              <div class="settings-tab-panel" id="tab-about">
                <h3 class="pane-heading">About KAVACH</h3>
                <p class="pane-sub">System architecture and forensic verification framework.</p>

                <div class="modal-about-card">
                  <div class="modal-about-meta">
                    <strong>KAVACH System Core</strong>
                    <span class="modal-version-tag">v2.4.0 Production</span>
                  </div>
                  <p class="modal-about-desc">
                    Automated multi-spectral forensic document verification kiosk designed for Smart India Hackathon. Verifies physical security features (guilloche lines, holograms, microtext, UV/IR fluorescent patterns, MRZ checksums) with local on-device machine learning inference and zero cloud latency.
                  </p>
                </div>
              </div>

            </div>
          </div>
        </div>
      `;
      document.body.appendChild(modal);

      // Bind modal backdrop click
      modal.addEventListener('click', e => {
        if (e.target === modal) window.closeSettingsModal();
      });

      // Bind dual-pane tab switching
      modal.querySelectorAll('.settings-nav-tab').forEach(tab => {
        tab.addEventListener('click', () => {
          const targetTabId = tab.getAttribute('data-tab');
          // Update tabs
          modal.querySelectorAll('.settings-nav-tab').forEach(t => t.classList.remove('active'));
          tab.classList.add('active');
          // Update panels
          modal.querySelectorAll('.settings-tab-panel').forEach(panel => {
            if (panel.id === 'tab-' + targetTabId) {
              panel.classList.add('active');
            } else {
              panel.classList.remove('active');
            }
          });
        });
      });

      // Bind visual theme preview cards
      modal.querySelectorAll('.theme-card-option').forEach(card => {
        card.addEventListener('click', () => {
          const val = card.getAttribute('data-theme-val');
          window.toggleTheme(val === 'dark');
        });
      });

      // Bind accent color swatches
      modal.querySelectorAll('.accent-swatch').forEach(swatch => {
        swatch.addEventListener('click', () => {
          window.setAccentColor(swatch.getAttribute('data-accent'));
        });
      });

      // Bind modal mode options
      modal.querySelectorAll('.modal-mode-option').forEach(btn => {
        btn.addEventListener('click', () => {
          window.setLocation(btn.getAttribute('data-location'));
        });
      });

      // Sync motion toggle
      const isReduced = localStorage.getItem('kavach-reduced-motion') === 'true';
      modal.querySelectorAll('.motion-toggle-input').forEach(input => {
        input.checked = isReduced;
        input.addEventListener('change', e => window.toggleReducedMotion(e.target.checked));
      });
    }
  }

  window.openSettingsModal = function () {
    ensureSettingsModalInDOM();
    const modal = document.getElementById('settingsModal');
    if (modal) {
      modal.classList.add('open');
      document.body.style.overflow = 'hidden';

      // Sync current theme card
      const currentTheme = document.documentElement.getAttribute('data-theme') || 'light';
      modal.querySelectorAll('.theme-card-option').forEach(card => {
        if (card.getAttribute('data-theme-val') === currentTheme) {
          card.classList.add('active');
        } else {
          card.classList.remove('active');
        }
      });

      // Sync current accent swatch
      const currentAccent = localStorage.getItem(ACCENT_KEY) || 'purple';
      window.setAccentColor(currentAccent);

      // Sync location
      updateLocationDisplay(localStorage.getItem(LOC_KEY) || defaultLoc);
    }
  };

  window.closeSettingsModal = function () {
    const modal = document.getElementById('settingsModal');
    if (modal) {
      modal.classList.remove('open');
      document.body.style.overflow = '';
    }
  };

  // Aliases
  window.openSettingsDrawer = window.openSettingsModal;
  window.closeSettingsDrawer = window.closeSettingsModal;

  // ── 6. REDUCED MOTION MANAGEMENT ──────────────────────────────────
  const MOTION_KEY = 'kavach-reduced-motion';
  window.toggleReducedMotion = function (reduce) {
    localStorage.setItem(MOTION_KEY, reduce ? 'true' : 'false');
    if (reduce) {
      document.body.classList.add('reduce-motion');
    } else {
      document.body.classList.remove('reduce-motion');
    }
    document.querySelectorAll('.motion-toggle-input').forEach(i => {
      i.checked = reduce;
    });
  };

  // ── 7. INITIALIZATION ON DOMContentLoaded ──────────────────────────
  document.addEventListener('DOMContentLoaded', () => {
    // 1. Sync theme cards and toggle checkboxes
    const currentTheme = localStorage.getItem(THEME_KEY) || 'light';
    document.querySelectorAll('.theme-card-option').forEach(card => {
      card.classList.toggle('active', card.getAttribute('data-theme-val') === currentTheme);
      card.addEventListener('click', () => {
        window.toggleTheme(card.getAttribute('data-theme-val') === 'dark');
      });
    });

    document.querySelectorAll('.theme-toggle-input').forEach(input => {
      input.checked = currentTheme === 'dark';
      input.addEventListener('change', e => window.toggleTheme(e.target.checked));
    });

    // 2. Sync accent swatches
    const currentAccent = localStorage.getItem(ACCENT_KEY) || 'purple';
    window.setAccentColor(currentAccent);
    document.querySelectorAll('.accent-swatch').forEach(sw => {
      sw.addEventListener('click', () => {
        window.setAccentColor(sw.getAttribute('data-accent'));
      });
    });

    // 3. Sync location / mode
    const activeLoc = localStorage.getItem(LOC_KEY) || defaultLoc;
    updateLocationDisplay(activeLoc);

    // 4. Bind context menu triggers
    document.querySelectorAll('.mode-chip-btn').forEach(btn => {
      btn.addEventListener('click', e => window.toggleModeMenu(e));
    });

    // 5. Bind context menu items
    document.querySelectorAll('.mode-menu-item').forEach(btn => {
      btn.addEventListener('click', () => {
        window.setLocation(btn.getAttribute('data-location') || btn.getAttribute('data-mode'));
      });
    });

    // 6. Global click outside listener to close mode menu
    document.addEventListener('click', e => {
      if (!e.target.closest('.mode-dropdown-wrapper')) {
        window.closeModeMenu();
      }
    });

    // 7. ESC key listener for modal and dropdown
    document.addEventListener('keydown', e => {
      if (e.key === 'Escape') {
        window.closeModeMenu();
        window.closeSettingsModal();
      }
    });

    // 8. Reduced motion init
    if (localStorage.getItem(MOTION_KEY) === 'true') {
      document.body.classList.add('reduce-motion');
      document.querySelectorAll('.motion-toggle-input').forEach(i => {
        i.checked = true;
      });
    }
  });
})();
