import htmx from 'htmx.org';
import Alpine from 'alpinejs';
import collapse from '@alpinejs/collapse';

// Expose HTMX globally
window.htmx = htmx;

// Register Alpine plugins and start
Alpine.plugin(collapse);
window.Alpine = Alpine;

// Initialize Alpine
Alpine.start();
