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
    document.querySelectorAll('.main-nav__link[data-nav]').forEach(function (link) {
      if (link.getAttribute('data-nav') === current) {
        link.classList.add('is-active');
      } else {
        link.classList.remove('is-active');
      }
    });
  }

  document.addEventListener('DOMContentLoaded', function () {
    Promise.all([
      loadPartial('[data-include="header"]', 'partials/header.html'),
      loadPartial('[data-include="footer"]', 'partials/footer.html')
    ]).then(function () {
      initNav();
      highlightActiveLink();
    });
  });
})();
