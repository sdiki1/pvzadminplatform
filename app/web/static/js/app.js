// Sidebar toggle for mobile
document.addEventListener('DOMContentLoaded', function() {
    const toggle = document.getElementById('sidebarToggle');
    const sidebar = document.getElementById('sidebar');
    const overlay = document.getElementById('sidebarOverlay');

    if (toggle) {
        toggle.addEventListener('click', function() {
            sidebar.classList.toggle('show');
            overlay.classList.toggle('show');
        });
    }

    if (overlay) {
        overlay.addEventListener('click', function() {
            sidebar.classList.remove('show');
            overlay.classList.remove('show');
        });
    }

    // Auto-dismiss alerts after 5s
    document.querySelectorAll('.alert-dismissible').forEach(function(alert) {
        setTimeout(function() {
            var bsAlert = bootstrap.Alert.getOrCreateInstance(alert);
            bsAlert.close();
        }, 5000);
    });
});

// HTMX configuration
document.body.addEventListener('htmx:configRequest', function(evt) {
    // Add CSRF token if present
    var csrfToken = document.querySelector('meta[name="csrf-token"]');
    if (csrfToken) {
        evt.detail.headers['X-CSRF-Token'] = csrfToken.content;
    }
});

// Show loading indicator on HTMX requests
document.body.addEventListener('htmx:beforeRequest', function(evt) {
    var target = evt.detail.target;
    if (target && target.closest('.table-container')) {
        target.style.opacity = '0.5';
    }
});

document.body.addEventListener('htmx:afterRequest', function(evt) {
    var target = evt.detail.target;
    if (target) {
        target.style.opacity = '1';
    }
});
