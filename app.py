import os
import logging
import time
from typing import Tuple
import psutil
import torch
import GPUtil
from contextlib import nullcontext

# Set offline environment variables
os.environ['HF_HUB_OFFLINE'] = '1'
os.environ['TRANSFORMERS_OFFLINE'] = '1'

import streamlit as st
from database import DocumentDatabase
from utils import CodeGenerator, PerformanceMonitor, clear_memory, GPUManager

# Configure logging
logging.basicConfig(
    filename='app_performance.log',
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

# Initialize performance monitor
monitor = PerformanceMonitor()

def get_system_stats():
    """Get current system statistics including GPU"""
    stats = {}
    
    # GPU Stats
    if torch.cuda.is_available():
        try:
            gpu = GPUtil.getGPUs()[0]
            stats.update({
                "GPU Device": torch.cuda.get_device_name(0),
                "GPU Memory": f"{gpu.memoryUsed:.0f}MB / {gpu.memoryTotal:.0f}MB",
                "GPU Util": f"{gpu.load*100:.1f}%",
                "CUDA Ver": torch.version.cuda
            })
        except Exception as e:
            logging.error(f"Error getting GPU stats: {e}")
            stats.update({"GPU Error": str(e)})
    
    # CPU Stats
    stats.update({
        "CPU Usage": f"{psutil.cpu_percent()}%",
        "RAM Usage": f"{psutil.virtual_memory().percent}%"
    })
    
    return stats

@st.cache_resource(ttl=3600)
def init_components() -> Tuple[DocumentDatabase, CodeGenerator]:
    """Initialize and cache the main components"""
    try:
        monitor.start("init_components")
        
        # Clear GPU memory before initialization
        if torch.cuda.is_available():
            GPUManager.clear_memory()
        
        db = DocumentDatabase().create_or_load_db()
        generator = CodeGenerator()
        
        monitor.end("init_components")
        return db, generator
        
    except Exception as e:
        logging.error(f"Error initializing components: {str(e)}")
        st.error(f"Error initializing components: {str(e)}")
        return None, None

@st.cache_data(ttl=300)
def get_similar_docs(db, query: str, k: int = 3):
    """Cache similarity search results"""
    monitor.start("similarity_search")
    docs = db.similarity_search(query, k=k)
    monitor.end("similarity_search")
    return docs

@st.cache_data(ttl=300)
def generate_code_cached(generator, prompt: str, max_length: int):
    """Cache code generation results"""
    monitor.start("code_generation")
    
    # Adjust max_length based on prompt length
    prompt_length = len(prompt.split())
    adjusted_length = max(500, prompt_length + 200)
    
    result = generator.generate_code(prompt, max_length=adjusted_length)
    monitor.end("code_generation")
    return result

def main():
    # Page configuration
    st.set_page_config(
        page_title="Code Assistant",
        page_icon="💻",
        layout="wide",
        initial_sidebar_state="expanded"
    )
    
    monitor.start("app_startup")
    
    if torch.cuda.is_available():
        st.sidebar.success(f"🚀 GPU Accelerated: {torch.cuda.get_device_name(0)}")
        st.sidebar.info(f"CUDA Version: {torch.version.cuda}")
    else:
        st.sidebar.warning("⚠️ Running on CPU (No GPU Detected)")
    
    st.title("Code Assistant (GPU Accelerated)")
    
    # Initialize components with loading indicator
    with st.spinner("Loading AI models..."):
        db, generator = init_components()
    
    if db is None or generator is None:
        st.stop()
    
    # Sidebar for settings and monitoring
    with st.sidebar:
        # System monitoring
        st.header("System Monitor")
        if st.checkbox("Show System Stats", value=False):
            stats_placeholder = st.empty()
            stats = get_system_stats()
            stats_text = "\n".join([f"{k}: {v}" for k, v in stats.items()])
            stats_placeholder.text(stats_text)
        
        # Settings
        st.header("Settings")
        language = st.selectbox(
            "Programming Language",
            ["Python", "JavaScript", "Java", "C++", "SQL"]
        )
        
        max_length = st.slider(
            "Maximum Code Length",
            min_value=100,
            max_value=1000,
            value=500,
            step=50
        )
        
        # Database management
        st.header("Database Management")
        if st.button("Refresh Documentation Database"):
            try:
                with st.spinner("Refreshing database..."):
                    monitor.start("refresh_database")
                    db = DocumentDatabase().refresh_database()
                    monitor.end("refresh_database")
                st.success("Database refreshed successfully!")
                if torch.cuda.is_available():
                    GPUManager.clear_memory()
            except Exception as e:
                logging.error(f"Error refreshing database: {str(e)}")
                st.error(f"Error refreshing database: {str(e)}")
    
    # Main interface
    st.header("Code Generation")
    
    # Two-column layout for input
    col1, col2 = st.columns([2, 1])
    
    with col1:
        user_query = st.text_area(
            "What code would you like to generate?",
            height=100,
            placeholder="Describe the code you need..."
        )
    
    with col2:
        st.markdown("### Options")
        generate_button = st.button("Generate Code", type="primary")
        include_explanation = st.checkbox("Include explanation", value=True)
        show_context = st.checkbox("Show reference docs", value=False)
    
    if generate_button and user_query:
        try:
            # Clear GPU memory before generation
            if torch.cuda.is_available():
                GPUManager.clear_memory()
            
            # Search documentation
            with st.spinner("Searching documentation..."):
                docs = get_similar_docs(db, user_query)
                context = "\n".join([doc.page_content for doc in docs])
            
            # Create prompt
            prompt = f"""
Language: {language}
Task: {user_query}

Reference Documentation:
{context}

Please generate code that follows best practices and includes comments.
"""
            
            # Generate code
            with st.spinner("Generating code..."):
                generated_code = generate_code_cached(generator, prompt, max_length)
                
                st.subheader("Generated Code")
                st.code(generated_code, language=language.lower())
                
                # Add copy button
                if st.button("📋 Copy Code"):
                    st.write(st.clipboard.copy(generated_code))
                    st.success("Code copied to clipboard!")
            
            # Generate explanation if requested
            if include_explanation:
                with st.spinner("Generating explanation..."):
                    explanation = generate_code_cached(
                        generator,
                        f"Explain this {language} code:\n{generated_code}",
                        max_length=300
                    )
                    st.subheader("Code Explanation")
                    st.write(explanation)
            
            # Show reference documentation if requested
            if show_context:
                with st.expander("Reference Documentation Used"):
                    for i, doc in enumerate(docs, 1):
                        st.markdown(f"**Reference {i}:**")
                        st.text(doc.page_content)
            
            # Clear GPU memory after generation
            if torch.cuda.is_available():
                GPUManager.clear_memory()
            
        except Exception as e:
            logging.error(f"Error during code generation: {str(e)}")
            st.error(f"An error occurred: {str(e)}")
    
    # Footer
    st.markdown("---")
    st.markdown(
        """
        <div style='text-align: center'>
            <p>Code Assistant - GPU Accelerated Mode</p>
            <p style='color: gray; font-size: 0.8em;'>
                Using local models for offline code generation
            </p>
        </div>
        """,
        unsafe_allow_html=True
    )
    
    monitor.end("app_startup")

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        logging.error(f"Application error: {str(e)}")
        st.error("An unexpected error occurred. Please check the logs for details.")