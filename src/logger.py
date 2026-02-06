"""
Logging configuration for CWtoSDP integration.

Provides structured logging with console and file output.
"""

import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional


def setup_logger(
    name: str = "cwtosdp",
    level: int = logging.INFO,
    log_dir: Optional[Path] = None,
    log_to_file: bool = True,
    log_to_console: bool = True,
) -> logging.Logger:
    """
    Set up a logger with console and optional file output.
    
    Args:
        name: Logger name.
        level: Logging level (e.g., logging.INFO, logging.DEBUG).
        log_dir: Directory for log files. Defaults to './logs'.
        log_to_file: Whether to log to a file.
        log_to_console: Whether to log to console.
    
    Returns:
        Configured logger instance.
    """
    logger = logging.getLogger(name)
    
    # Avoid duplicate handlers if logger already configured
    if logger.handlers:
        return logger
    
    logger.setLevel(level)
    
    # Create formatter
    formatter = logging.Formatter(
        fmt="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )
    
    # Console handler
    if log_to_console:
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(level)
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)
    
    # File handler (Rotating)
    if log_to_file:
        log_dir = log_dir or Path("./logs")
        log_dir.mkdir(parents=True, exist_ok=True)
        
        # Use a fixed name for rotation to work correctly
        log_file = log_dir / "cwtosdp.log"
        
        from logging.handlers import RotatingFileHandler
        
        # Max 5MB per file, keep 3 backup revisions
        file_handler = RotatingFileHandler(
            log_file, 
            maxBytes=5*1024*1024, 
            backupCount=3, 
            encoding="utf-8"
        )
        file_handler.setLevel(level)
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
    
    return logger


def get_logger(name: str = "cwtosdp") -> logging.Logger:
    """
    Get an existing logger or create a new one.
    
    Args:
        name: Logger name (use dotted names for hierarchy, e.g., 'cwtosdp.cw_client').
    
    Returns:
        Logger instance.
    """
    return logging.getLogger(name)


# Create default application logger
app_logger = setup_logger()

