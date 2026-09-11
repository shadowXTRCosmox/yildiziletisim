import socket
import threading
import json

# Online kullanıcılar: { "kullanici_adi": { "socket": conn, "pub_key": pem_bytes } }
clients = {}

def handle_client(conn, addr):
    username = None
    try:
        # 1. Kayıt El Sıkışması (Kullanıcı adı ve Public Key al)
        init_data = conn.recv(4096).decode('utf-8')
        payload = json.loads(init_data)
        username = payload["username"]
        pub_key_pem = payload["pub_key"]

        clients[username] = {"socket": conn, "pub_key": pub_key_pem}
        print(f"[+] '{username}' bağlandı ({addr[0]})")

        while True:
            data = conn.recv(8192).decode('utf-8')
            if not data:
                break
            
            msg_obj = json.loads(data)
            action = msg_obj.get("action")

            # A. Aktif Kullanıcı Listesini Gönder
            if action == "get_users":
                user_list = {u: info["pub_key"] for u, info in clients.items() if u != username}
                conn.send(json.dumps({"action": "user_list", "users": user_list}).encode('utf-8'))

            # B. Mesaj Yönlendir (Kör Aktarım)
            elif action == "send_msg":
                target = msg_obj["target"]
                if target in clients:
                    target_sock = clients[target]["socket"]
                    forward_payload = json.dumps({
                        "action": "incoming_msg",
                        "sender": username,
                        "encrypted_payload": msg_obj["encrypted_payload"]
                    })
                    target_sock.send(forward_payload.encode('utf-8'))

    except Exception:
        pass
    finally:
        if username and username in clients:
            del clients[username]
            print(f"[-] '{username}' ayrıldı.")
        conn.close()

def main():
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.bind(("0.0.0.0", 5000))
    server.bind_time = True
    server.listen(10)
    print("=== GİZLİ REHBER SUNUCUSU BÖLGESİ DİNLENİYOR (PORT 5000) ===")

    while True:
        conn, addr = server.accept()
        threading.Thread(target=handle_client, args=(conn, addr), daemon=True).start()

if __name__ == "__main__":
    main()