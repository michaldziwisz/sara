use std::ffi::{CStr, CString};
use std::os::raw::c_char;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{mpsc, Arc};
use std::thread;

type MixCallback = Option<unsafe extern "C" fn(*const c_char, *const c_char)>;

enum Message {
    Work(String, String),
    Shutdown,
}

#[repr(C)]
pub struct SaraMixExecutor {
    alive: Arc<AtomicBool>,
    tx: mpsc::Sender<Message>,
    thread: Option<thread::JoinHandle<()>>,
}

fn worker(rx: mpsc::Receiver<Message>, alive: Arc<AtomicBool>, callback: MixCallback) {
    while alive.load(Ordering::Relaxed) {
        let msg = match rx.recv() {
            Ok(value) => value,
            Err(_) => break,
        };
        match msg {
            Message::Work(playlist_id, item_id) => {
                if let Some(cb) = callback {
                    let playlist = CString::new(playlist_id).unwrap_or_else(|_| CString::new("").unwrap());
                    let item = CString::new(item_id).unwrap_or_else(|_| CString::new("").unwrap());
                    unsafe {
                        cb(playlist.as_ptr(), item.as_ptr());
                    }
                }
            }
            Message::Shutdown => break,
        }
    }
}

#[no_mangle]
pub extern "C" fn sara_mix_executor_create(callback: MixCallback) -> *mut SaraMixExecutor {
    let (tx, rx) = mpsc::channel::<Message>();
    let alive = Arc::new(AtomicBool::new(true));
    let alive_thread = Arc::clone(&alive);
    let thread = thread::spawn(move || worker(rx, alive_thread, callback));
    Box::into_raw(Box::new(SaraMixExecutor {
        alive,
        tx,
        thread: Some(thread),
    }))
}

#[no_mangle]
pub extern "C" fn sara_mix_executor_enqueue(handle: *mut SaraMixExecutor, playlist_id: *const c_char, item_id: *const c_char) {
    if handle.is_null() || playlist_id.is_null() || item_id.is_null() {
        return;
    }
    let executor = unsafe { &*handle };
    if !executor.alive.load(Ordering::Relaxed) {
        return;
    }
    let pl = unsafe { CStr::from_ptr(playlist_id) }.to_string_lossy().into_owned();
    let it = unsafe { CStr::from_ptr(item_id) }.to_string_lossy().into_owned();
    let _ = executor.tx.send(Message::Work(pl, it));
}

#[no_mangle]
pub extern "C" fn sara_mix_executor_destroy(handle: *mut SaraMixExecutor) {
    if handle.is_null() {
        return;
    }
    let mut executor = unsafe { Box::from_raw(handle) };
    executor.alive.store(false, Ordering::Relaxed);
    let _ = executor.tx.send(Message::Shutdown);
    if let Some(thread) = executor.thread.take() {
        let _ = thread.join();
    }
}

