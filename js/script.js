/**
 * Local Hustlers — shared site script
 *
 * Loads the shared header and footer from partials/header.html and
 * partials/footer.html into every page, then wires up the mobile nav
 * toggle and highlights the current page's nav link. This means the
 * header/footer markup only has to be edited in one place.
 *
 * Note: loading partials relies on fetch(), which requires the site to
 * be served over http(s) (a local dev server, or any real web host).
 * Opening a page directly from disk (file://) will not load the
 * header/footer because browsers block fetch() for local files.
 */
(function () {
  'use strict';

  function loadPartial(selector, url) {
    var target = document.querySelector(selector);
    if (!target) return Promise.resolve();

    return fetch(url)
      .then(function (response) {
        if (!response.ok) throw new Error('Failed to load ' + url);
        return response.text();
      })
      .then(function (html) {
        target.innerHTML = html;
      })
      .catch(function (error) {
        console.error(error);
        target.innerHTML =
          '<p style="padding:16px;color:#b00;">Could not load ' +
          url +
          '. Make sure the site is running on a local server (not opened directly as a file).</p>';
      });
  }

  function initNav() {
    var toggle = document.getElementById('navToggle');
    var nav = document.getElementById('mainNav');

    if (!toggle || !nav) return;

    function openNav() {
      nav.classList.add('is-open');
      toggle.setAttribute('aria-expanded', 'true');
    }

    function closeNav() {
      nav.classList.remove('is-open');
      toggle.setAttribute('aria-expanded', 'false');
    }

    function isOpen() {
      return nav.classList.contains('is-open');
    }

    toggle.addEventListener('click', function (event) {
      event.stopPropagation();
      if (isOpen()) {
        closeNav();
      } else {
        openNav();
      }
    });

    nav.querySelectorAll('.main-nav__link').forEach(function (link) {
      link.addEventListener('click', closeNav);
    });

    document.addEventListener('click', function (event) {
      if (isOpen() && !nav.contains(event.target) && event.target !== toggle) {
        closeNav();
      }
    });

    document.addEventListener('keydown', function (event) {
      if (event.key === 'Escape' && isOpen()) {
        closeNav();
      }
    });

    window.addEventListener('resize', function () {
      if (window.innerWidth > 900 && isOpen()) {
        closeNav();
      }
    });
  }

  function highlightActiveLink() {
    var current = window.location.pathname.split('/').pop() || 'index.html';

    // Nav links: highlight the current page and stop it from re-navigating
    // to (reloading) the page you're already on.
    document.querySelectorAll('.main-nav__link[data-nav]').forEach(function (link) {
      if (link.getAttribute('data-nav') === current) {
        link.classList.add('is-active');
        link.setAttribute('aria-current', 'page');
        link.addEventListener('click', function (event) {
          event.preventDefault();
        });
      } else {
        link.classList.remove('is-active');
      }
    });

    // Logo link: same fix so clicking it on the home page doesn't reload it.
    var brandLink = document.querySelector('.brand[href]');
    if (brandLink && brandLink.getAttribute('href').split('/').pop() === current) {
      brandLink.setAttribute('aria-current', 'page');
      brandLink.addEventListener('click', function (event) {
        event.preventDefault();
      });
    }
  }

  // ---------------------------------------------------------------------
  // Page transition: the overlay itself lives directly in each page's
  // HTML (templates/_page_transition.html.j2) so it's present from the
  // very first paint — this just handles covering the screen again,
  // with the same downward motion, right before navigating to another
  // page. Uses event delegation on `document` so it also catches clicks
  // on the header/footer nav links, which get added later once those
  // partials finish loading.
  // ---------------------------------------------------------------------
  var TRANSITION_MS = 600;

  function initPageTransition() {
    var overlay = document.querySelector('.page-transition');
    if (!overlay) return;

    var prefersReducedMotion =
      window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    if (prefersReducedMotion) return; // let links navigate instantly, no delay

    function isInternalPageLink(link) {
      if (!link || !link.getAttribute('href')) return false;
      if (link.hasAttribute('download')) return false;
      var targetAttr = link.getAttribute('target');
      if (targetAttr && targetAttr !== '_self') return false;

      var url;
      try {
        url = new URL(link.href, window.location.href);
      } catch (error) {
        return false;
      }
      if (url.origin !== window.location.origin) return false;
      if (url.protocol !== 'http:' && url.protocol !== 'https:') return false;

      var current = window.location.pathname.split('/').pop() || 'index.html';
      var target = url.pathname.split('/').pop() || 'index.html';
      if (target === current) return false; // same page — nothing to transition to
      if (!/\.html?$/i.test(target)) return false; // only intercept links to other site pages

      return true;
    }

    document.addEventListener('click', function (event) {
      if (event.defaultPrevented) return;
      if (event.button !== 0) return; // left click only
      if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;

      var link = event.target.closest ? event.target.closest('a') : null;
      if (!isInternalPageLink(link)) return;

      event.preventDefault();
      var href = link.href;

      // Snap the overlay above the viewport with no transition, then
      // animate it back down to cover the screen — the mirror image of
      // the reveal-on-load animation, so the motion always reads as one
      // continuous downward sweep no matter which direction it's going.
      overlay.style.animation = 'none';
      overlay.style.transition = 'none';
      overlay.style.transform = 'translateY(-100%)';
      overlay.offsetHeight; // force a reflow so the line above takes effect first
      overlay.style.transition = 'transform ' + TRANSITION_MS + 'ms cubic-bezier(0.65, 0, 0.35, 1)';

      requestAnimationFrame(function () {
        overlay.style.transform = 'translateY(0)';
      });

      window.setTimeout(function () {
        window.location.href = href;
      }, TRANSITION_MS);
    });
  }

  document.addEventListener('DOMContentLoaded', function () {
    initPageTransition();

    Promise.all([
      loadPartial('[data-include="header"]', 'partials/header.html'),
      loadPartial('[data-include="footer"]', 'partials/footer.html')
    ]).then(function () {
      initNav();
      highlightActiveLink();
    });
  });
})();
