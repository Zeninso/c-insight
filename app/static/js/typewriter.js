function typeWriter(elementId, text, speed = 100) {
    let i = 0;
    const elem = document.getElementById(elementId);
  elem.innerHTML = ""; // Clear existing content
    
    function type() {
    if (i < text.length) {
        elem.innerHTML += text.charAt(i);
        i++;
        setTimeout(type, speed);
    }
    }
    
    type();
}

// Optional: Auto-start on page load for specific elements
document.addEventListener('DOMContentLoaded', function() {
    const elements = document.querySelectorAll('[data-typewriter]');
    elements.forEach(el => {
    const text = el.textContent;
    el.innerHTML = ''; // Clear original text
    typeWriter(el.id, text, el.dataset.speed || 100);
    });
});