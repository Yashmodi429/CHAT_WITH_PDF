
import os
import pdfplumber
import google.generativeai as genai
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain_google_genai import GoogleGenerativeAIEmbeddings
from langchain_community.vectorstores import Chroma
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain.chains import ConversationalRetrievalChain
from langchain.memory import ConversationBufferMemory

from google.colab import userdata
os.environ["GOOGLE_API_KEY"] = userdata.get("GEMINI_API_KEY")

import streamlit as st
import os
import tempfile
from session_4_rag_backend import (
    setup_api_key,
    upload_pdf,
    parse_pdf,
    create_document_chunks,
    init_embedding_model,
    embed_documents,
    store_embeddings,
    get_context_from_chunks,
    query_with_full_context
)

# Page configuration
st.set_page_config(
    page_title="RAG Chatbot with Gemini",
    page_icon="📚",
    layout="wide"
)

# Session state initialization
if "conversation" not in st.session_state:
    st.session_state.conversation = []
if "vectorstore" not in st.session_state:
    st.session_state.vectorstore = None
if "embedding_model" not in st.session_state:
    st.session_state.embedding_model = None
if "processed_files" not in st.session_state:
    st.session_state.processed_files = []


def main():
    # Sidebar for API key and file upload
    with st.sidebar:
        st.title("RAG Chatbot")
        st.subheader("Configuration")

        # API Key input
        api_key = st.text_input("Enter Gemini API Key:", type="password")

        if api_key:
            if st.button("Set API Key"):
                setup_api_key(api_key)
                st.success("API Key set successfully!")

        st.divider()

        # File uploader
        st.subheader("Upload Documents")
        uploaded_files = st.file_uploader("Upload PDF files", type="pdf", accept_multiple_files=True)

        if uploaded_files:
            if st.button("Process Documents"):
                process_documents(uploaded_files)

        # Display processed files
        if st.session_state.processed_files:
            st.subheader("Processed Documents")
            for file in st.session_state.processed_files:
                st.write(f"- {file}")

        st.divider()

        # Advanced options
        with st.expander("Advanced Options"):
            st.slider("Number of chunks to retrieve (k)", min_value=1, max_value=10, value=3, key="k_value")
            st.slider("Temperature", min_value=0.0, max_value=1.0, value=0.2, step=0.1, key="temperature")

    # Main content area
    st.title("Retrieval Augmented Generation Chatbot")

    # Check if vectorstore is ready
    if st.session_state.vectorstore is None:
        st.info("Please upload and process documents to start chatting.")

        # Example usage instructions
        with st.expander("How to use this app"):
            st.markdown("""
            1. Enter your Gemini API Key in the sidebar
            2. Upload one or more PDF documents
            3. Click "Process Documents" to analyze them
            4. Ask questions about the documents in the chat

            The system will use Retrieval Augmented Generation to provide accurate answers based on the content of your documents.
            """)

    else:
        # Chat interface
        display_chat()

        # User input for queries
        user_query = st.chat_input("Ask a question about your documents...")
        if user_query:
            handle_user_query(user_query)


def process_documents(uploaded_files):
    """Process uploaded PDF documents and create the vector store"""
    try:
        # Initialize progress tracking
        progress_bar = st.sidebar.progress(0)
        status_text = st.sidebar.empty()

        # Initialize embedding model if not already done
        if st.session_state.embedding_model is None:
            status_text.text("Initializing embedding model...")
            st.session_state.embedding_model = init_embedding_model()
            if st.session_state.embedding_model is None:
                st.sidebar.error("Failed to initialize embedding model. Check your API key.")
                return

        # Process each uploaded file
        all_chunks = []
        processed_file_names = []

        for i, uploaded_file in enumerate(uploaded_files):
            # Update progress
            progress = (i / len(uploaded_files)) * 100
            progress_bar.progress(int(progress))
            status_text.text(f"Processing {uploaded_file.name}...")

            # Save uploaded file temporarily
            with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp_file:
                tmp_file.write(uploaded_file.getvalue())
                pdf_path = tmp_file.name

            # Process the PDF
            pdf_file = upload_pdf(pdf_path)
            if not pdf_file:
                st.sidebar.warning(f"Failed to process {uploaded_file.name}")
                continue

            # Parse PDF to extract text
            text = parse_pdf(pdf_file)
            if not text:
                st.sidebar.warning(f"Failed to extract text from {uploaded_file.name}")
                continue

            # Create document chunks
            chunks = create_document_chunks(text)
            if not chunks:
                st.sidebar.warning(f"Failed to create chunks from {uploaded_file.name}")
                continue

            # Add metadata to chunks
            chunks_with_metadata = []
            for chunk in chunks:
                chunks_with_metadata.append({
                    "content": chunk,
                    "source": uploaded_file.name
                })

            all_chunks.extend(chunks_with_metadata)
            processed_file_names.append(uploaded_file.name)

            # Clean up temporary file
            os.unlink(pdf_path)

        # Update progress
        progress_bar.progress(100)
        status_text.text("Creating vector database...")

        # Store embeddings in vector database
        if all_chunks:
            texts = [chunk["content"] for chunk in all_chunks]
            metadatas = [{"source": chunk["source"]} for chunk in all_chunks]

            vectorstore = store_embeddings(
                st.session_state.embedding_model,
                texts,
                persist_directory="./streamlit_chroma_db"
            )

            if vectorstore:
                st.session_state.vectorstore = vectorstore
                st.session_state.processed_files = processed_file_names
                status_text.text("Processing complete!")
                st.sidebar.success(f"Successfully processed {len(processed_file_names)} documents")
            else:
                st.sidebar.error("Failed to create vector database")
        else:
            st.sidebar.error("No valid chunks extracted from documents")

        # Clear progress indicators
        progress_bar.empty()
        status_text.empty()

    except Exception as e:
        st.sidebar.error(f"Error processing documents: {str(e)}")


def handle_user_query(query):
    """Process a user query and display the response"""
    if st.session_state.vectorstore is None:
        st.error("Please process documents before asking questions")
        return

    # Add user message to conversation
    st.session_state.conversation.append({"role": "user", "content": query})

    # Display "thinking" message
    thinking_placeholder = st.empty()
    thinking_placeholder.info("🤔 Thinking...")

    try:
        # Retrieve k value from session state
        k = st.session_state.k_value
        temperature = st.session_state.temperature

        # Query the RAG system
        response, context, chunks = query_with_full_context(
            query,
            st.session_state.vectorstore,
            k=k,
            temperature=temperature
        )

        # Add assistant response to conversation
        st.session_state.conversation.append({"role": "assistant", "content": response, "context": context})

        # Clear thinking message
        thinking_placeholder.empty()

        # Refresh the chat display
        display_chat()

    except Exception as e:
        thinking_placeholder.empty()
        error_msg = f"Error generating response: {str(e)}"
        st.session_state.conversation.append({"role": "assistant", "content": error_msg})
        display_chat()


def display_chat():
    """Display the chat conversation"""
    for message in st.session_state.conversation:
        if message["role"] == "user":
            with st.chat_message("user"):
                st.write(message["content"])
        else:
            with st.chat_message("assistant"):
                st.write(message["content"])

                # Display context info in an expander if available
                if "context" in message and message["context"]:
                    with st.expander("View source context"):
                        st.text(message["context"])


def reset_conversation():
    """Reset the conversation history"""
    st.session_state.conversation = []


if __name__ == "__main__":
    main()

!streamlit run rag_streamlit.py --server.port=8989 &>./logs.txt &
