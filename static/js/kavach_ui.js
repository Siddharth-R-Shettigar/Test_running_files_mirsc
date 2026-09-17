/**
 * KAVACH — UI Framework Core
 * Handles Theme (Dark/Light), Operational Location, and Floating Drawer interactions
 */
(function () {
  'use strict';

  // ── 1. THEME MANAGEMENT (PERSISTENT IN LOCALSTORAGE) ──────────────
  const THEME_KEY = 'kavach-theme';
  const savedTheme = localStorage.getItem(THEME_KEY) || 'light';
  document.documentElement.setAttribute('data-theme', savedTheme);

  window.toggleTheme = function (isDark) {
    const theme = isDark ? 'dark' : 'light';
    document.documentElement.setAttribute('data-theme', theme);
    localStorage.setItem(THEME_KEY, theme);
    // sync all toggle checkboxes
    document.querySelectorAll('.theme-toggle-input').forEach(input => {
      input.checked = isDark;
    });
  };

  // ── 2. OPERATIONAL LOCATION MANAGEMENT ────────────────────────────
  const LOC_KEY = 'kavach-operational-location';
  const defaultLoc = 'Airport Kiosk T3';
  const savedLoc = localStorage.getItem(LOC_KEY) || defaultLoc;

  function updateLocationDisplay(locName) {
    document.querySelectorAll('.loc-display-text').forEach(el => {
      el.textContent = locName;
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
  };

  // ── 3. FLOATING SETTINGS DRAWER ───────────────────────────────────
  window.openSettingsDrawer = function () {
    const drawer = document.getElementById('settingsDrawer');
    if (drawer) {
      drawer.classList.add('open');
      document.body.style.overflow = 'hidden';
    } else {
      window.location.href = '/settings';
    }
  };

  window.closeSettingsDrawer = function () {
    const drawer = document.getElementById('settingsDrawer');
    if (drawer) {
      drawer.classList.remove('open');
      document.body.style.overflow = '';
    }
  };

  // ── 4. REDUCED MOTION MANAGEMENT ──────────────────────────────────
  const MOTION_KEY = 'kavach-reduced-motion';
  window.toggleReducedMotion = function (reduce) {
    localStorage.setItem(MOTION_KEY, reduce ? 'true' : 'false');
    if (reduce) {
      document.body.classList.add('reduce-motion');
    } else {
      document.body.classList.remove('reduce-motion');
    }
  };

  // Initialize on DOMContentLoaded
  document.addEventListener('DOMContentLoaded', () => {
    // Sync theme checkbox
    const currentTheme = localStorage.getItem(THEME_KEY) || 'light';
    document.querySelectorAll('.theme-toggle-input').forEach(input => {
      input.checked = currentTheme === 'dark';
      input.addEventListener('change', e => window.toggleTheme(e.target.checked));
    });

    // Sync location
    updateLocationDisplay(localStorage.getItem(LOC_KEY) || defaultLoc);
    document.querySelectorAll('.loc-option-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        window.setLocation(btn.getAttribute('data-location'));
      });
    });

    // Close drawer on backdrop click or ESC
    const drawer = document.getElementById('settingsDrawer');
    if (drawer) {
      drawer.addEventListener('click', e => {
        if (e.target === drawer) window.closeSettingsDrawer();
      });
    }
    document.addEventListener('keydown', e => {
      if (e.key === 'Escape') window.closeSettingsDrawer();
    });

    // Reduced motion init
    if (localStorage.getItem(MOTION_KEY) === 'true') {
      document.body.classList.add('reduce-motion');
      document.querySelectorAll('.motion-toggle-input').forEach(i => i.checked = true);
    }
  });
})();

