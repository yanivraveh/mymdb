document.addEventListener('DOMContentLoaded', function () {
    const chatBubble = document.querySelector('.chat-bubble');
    const chatWindow = document.querySelector('.chat-window');
    const chatClose = document.querySelector('.chat-close');
    const chatForm = document.getElementById('chat-form');
    const chatInput = document.getElementById('chat-input');
    const chatMessages = document.getElementById('chat-messages');
    
    let conversationHistory = [];

    // --- Load state from sessionStorage on page load ---
    function loadChatState() {
        const isOpen = sessionStorage.getItem('chatWidgetOpen') === 'true';
        if (isOpen) {
            chatWindow.classList.add('open');
        }

        const history = JSON.parse(sessionStorage.getItem('chatHistory'));
        if (history && history.length > 0) {
            conversationHistory = history;
            chatMessages.innerHTML = ''; // Clear initial message
            conversationHistory.forEach(item => {
                appendMessage(item.message, item.sender, false); // Don't save again
            });
        }
    }

    // --- Save state to sessionStorage ---
    function saveChatState() {
        sessionStorage.setItem('chatWidgetOpen', chatWindow.classList.contains('open'));
        sessionStorage.setItem('chatHistory', JSON.stringify(conversationHistory));
    }
    
    chatBubble.addEventListener('click', () => {
        chatWindow.classList.toggle('open');
        saveChatState();
    });

    chatClose.addEventListener('click', () => {
        chatWindow.classList.remove('open');
        saveChatState();
    });

    chatForm.addEventListener('submit', function (e) {
        e.preventDefault();
        const userMessage = chatInput.value.trim();

        if (userMessage) {
            appendMessage({text: userMessage}, 'user');
            chatInput.value = '';
            
            // Pass the current history along with the message
            const currentHistoryForAPI = conversationHistory.map(item => {
                // We only need to send a simplified version of the history
                return {
                    role: item.sender === 'user' ? 'user' : 'model',
                    parts: [{ text: JSON.stringify(item.message) }]
                }
            });

            fetch('/api/chatbot/', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ 
                    message: userMessage,
                    history: currentHistoryForAPI
                })
            })
            .then(response => response.json())
            .then(data => {
                appendMessage(data, 'assistant');
            })
            .catch(error => {
                console.error('Error:', error);
                appendMessage({text: 'Sorry, something went wrong. Please try again.'}, 'assistant');
            });
        }
    });

    function appendMessage(messageData, sender, save = true) {
        const messageElement = document.createElement('div');
        messageElement.classList.add('message', sender);

        const textElement = document.createElement('div');
        textElement.textContent = messageData.text || messageData;
        messageElement.appendChild(textElement);

        if (messageData.movies && messageData.movies.length > 0) {
            const movieList = document.createElement('ul');
            movieList.classList.add('chat-movie-list');
            messageData.movies.forEach(movie => {
                const movieItem = document.createElement('li');
                const movieLink = document.createElement('a');
                movieLink.href = movie.url;
                let movieText = movie.title;
                if (movie.release_year) {
                    movieText += ` (${movie.release_year})`;
                }
                movieLink.textContent = movieText;
                movieItem.appendChild(movieLink);
                movieList.appendChild(movieItem);
            });
            messageElement.appendChild(movieList);
        }
        
        chatMessages.appendChild(messageElement);
        chatMessages.scrollTop = chatMessages.scrollHeight;

        if (save) {
            conversationHistory.push({ message: messageData, sender: sender });
            saveChatState();
        }
    }
    
    loadChatState(); // Load the state when the DOM is ready
});
