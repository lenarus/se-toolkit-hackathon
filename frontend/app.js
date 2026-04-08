/**
 * CF Compare - Frontend JavaScript
 * Handles API calls and dynamic table rendering.
 */

// Backend API URL — uses relative path so nginx proxy routes it correctly.
// This works from any device (localhost, IP, or domain).
const API_BASE = '/api';

/**
 * Main function to compare users
 * Called when the "Compare" button is clicked
 */
async function compareUsers() {
    // Get handles from input
    const handlesInput = document.getElementById('handles-input');
    const handles = handlesInput.value.trim();

    // Validation
    if (!handles) {
        showError('Please enter at least one handle');
        return;
    }

    // Hide previous results and errors
    hideError();
    hideResults();
    showLoading();

    try {
        // Make API request via nginx proxy (relative URL)
        const response = await fetch(`${API_BASE}/compare?handles=${encodeURIComponent(handles)}`);

        if (!response.ok) {
            const errorData = await response.json();
            throw new Error(errorData.detail || 'Failed to fetch data');
        }

        const data = await response.json();

        // Hide loading and show results
        hideLoading();
        displayResults(data.users);

    } catch (error) {
        hideLoading();
        showError(error.message);
        console.error('Error:', error);
    }
}

/**
 * Display comparison results in the table
 * @param {Array} users - Array of user comparison objects
 */
function displayResults(users) {
    const table = document.getElementById('comparison-table');
    const thead = table.querySelector('thead tr');
    const tbody = table.querySelector('tbody');

    // Clear previous data
    thead.innerHTML = '<th>Metric</th>';
    tbody.innerHTML = '';

    // Check if some users were not found
    const notFoundUsers = users.filter(u => !u.found);
    if (notFoundUsers.length > 0) {
        const warningNames = notFoundUsers.map(u => u.handle).join(', ');
        showError(`⚠️ User(s) not found: ${warningNames}. Showing results for found users only.`);
    }

    // Add user columns to header
    users.forEach(user => {
        const th = document.createElement('th');
        th.textContent = user.handle + (user.found ? '' : ' ❌');
        thead.appendChild(th);
    });

    // Define metrics to display
    const metrics = [
        { key: 'rating', label: 'Current Rating' },
        { key: 'rank', label: 'Current Rank' },
        { key: 'maxRating', label: 'Max Rating' },
        { key: 'maxRank', label: 'Max Rank' },
        { key: 'solved_count', label: 'Solved Problems' }
    ];

    // Add rows for each metric
    metrics.forEach(metric => {
        const tr = document.createElement('tr');

        // Metric label
        const tdLabel = document.createElement('td');
        tdLabel.textContent = metric.label;
        tr.appendChild(tdLabel);

        // User values
        users.forEach(user => {
            const td = document.createElement('td');
            if (!user.found) {
                td.textContent = 'N/A';
                td.style.color = '#ff4757';
                td.style.fontStyle = 'italic';
            } else {
                const value = user[metric.key];
                td.textContent = value !== null && value !== undefined ? value : 'N/A';
            }
            tr.appendChild(td);
        });

        tbody.appendChild(tr);
    });

    // Show results section
    document.getElementById('results-section').classList.remove('hidden');
}

/**
 * Show error message
 * @param {string} message - Error message to display
 */
function showError(message) {
    const errorDiv = document.getElementById('error-message');
    errorDiv.textContent = message;
    errorDiv.classList.remove('hidden');
}

/**
 * Hide error message
 */
function hideError() {
    document.getElementById('error-message').classList.add('hidden');
}

/**
 * Show loading indicator
 */
function showLoading() {
    document.getElementById('loading').classList.remove('hidden');
}

/**
 * Hide loading indicator
 */
function hideLoading() {
    document.getElementById('loading').classList.add('hidden');
}

/**
 * Hide results section
 */
function hideResults() {
    document.getElementById('results-section').classList.add('hidden');
}

// Allow Enter key to trigger comparison
document.addEventListener('DOMContentLoaded', () => {
    const handlesInput = document.getElementById('handles-input');
    handlesInput.addEventListener('keypress', (e) => {
        if (e.key === 'Enter') {
            compareUsers();
        }
    });
});
