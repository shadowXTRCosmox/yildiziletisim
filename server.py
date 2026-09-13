import asyncio
import json
import os
import psycopg2
import websockets

# --- VERİTABANI BAĞLANTISI ---
DATABASE_URL = os.environ.get("DATABASE_URL") or "postgresql://postgres.qbpnqccxvacbgcaioizf:emir8514%2112@aws-0-ap-northeast-1.pooler.supabase.com:6543/postgres"

conn = psycopg2.connect(DATABASE_URL)
conn.autocommit = True  
cursor = conn.cursor()

cursor.execute("""
    CREATE TABLE IF NOT EXISTS users (
        username TEXT PRIMARY KEY,
        password TEXT,
        public_key TEXT,
        color TEXT,
        avatar TEXT,
        bio TEXT,
        theme TEXT
    )
""")
cursor.execute("""
    CREATE TABLE IF NOT EXISTS messages (
        id SERIAL PRIMARY KEY,
        sender TEXT,
        target TEXT,
        encrypted_key TEXT,
        nonce TEXT,
        ciphertext TEXT,
        color TEXT,
        timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
""")
cursor.execute("""
    CREATE TABLE IF NOT EXISTS friends (
        user1 TEXT,
        user2 TEXT,
        status TEXT
    )
""")

# Bağlı olan kullanıcıları tutar: {username: {"websocket": ws, "avatar": av, "color": col, "bio": bi}}
connected_clients = {}

async def broadcast_user_lists():
    if not connected_clients:
        return
    
    online_users = list(connected_clients.keys())
    avatars = {u: info["avatar"] for u, info in connected_clients.items()}
    colors = {u: info["color"] for u, info in connected_clients.items()}
    bios = {u: info["bio"] for u, info in connected_clients.items()}

    for username, info in list(connected_clients.items()):
        try:
            ws = info["websocket"]

            cursor.execute("SELECT user1, user2 FROM friends WHERE (user1 = %s OR user2 = %s) AND status = 'accepted'", (username, username))
            friends = []
            for u1, u2 in cursor.fetchall():
                friends.append(u2 if u1 == username else u1)

            cursor.execute("SELECT user1 FROM friends WHERE user2 = %s AND status = 'pending'", (username,))
            requests = [row[0] for row in cursor.fetchall()]

            response = {
                "type": "user_list_response",
                "users": online_users,
                "friends": friends,
                "requests": requests,
                "avatars": avatars,
                "colors": colors,
                "bios": bios,
            }
            await ws.send(json.dumps(response))
        except Exception:
            pass

async def handler(websocket):
    current_user = None
    try:
        async for message in websocket:
            data = json.loads(message)
            msg_type = data.get("type")

            if msg_type == "register":
                username = data.get("username")
                password = data.get("password")
                public_key = data.get("public_key")
                color = data.get("color", "#89b4fa")
                avatar = data.get("avatar", "")
                bio = data.get("bio", "")
                theme = data.get("theme", "Mavi Tonları (Varsayılan)")

                cursor.execute("SELECT * FROM users WHERE username = %s", (username,))
                if cursor.fetchone():
                    await websocket.send(json.dumps({"status": "error", "message": "Bu kullanıcı adı zaten alınmış!"}))
                else:
                    cursor.execute("INSERT INTO users VALUES (%s, %s, %s, %s, %s, %s, %s)", (username, password, public_key, color, avatar, bio, theme))
                    await websocket.send(json.dumps({"status": "success", "message": "Kayıt başarılı!"}))

            elif msg_type == "login":
                username = data.get("username")
                password = data.get("password")

                cursor.execute("SELECT * FROM users WHERE username = %s AND password = %s", (username, password))
                user = cursor.fetchone()
                if user:
                    current_user = username
                    
                    cursor.execute("SELECT color, avatar, bio, theme FROM users WHERE username = %s", (current_user,))
                    u_data = cursor.fetchone()
                    db_color, db_avatar, db_bio, db_theme = u_data if u_data else ("#89b4fa", "", "", "Mavi Tonları (Varsayılan)")

                    connected_clients[current_user] = {
                        "websocket": websocket,
                        "avatar": db_avatar,
                        "color": db_color,
                        "bio": db_bio
                    }

                    await websocket.send(json.dumps({
                        "status": "success", 
                        "message": "Giriş başarılı",
                        "color": db_color,
                        "avatar": db_avatar,
                        "bio": db_bio,
                        "theme": db_theme
                    }))
                    
                    await broadcast_user_lists()
                else:
                    await websocket.send(json.dumps({"status": "error", "message": "Geçersiz kullanıcı adı veya şifre!"}))

            elif msg_type == "get_users":
                if not current_user: continue
                
                online_users = list(connected_clients.keys())
                avatars = {u: info["avatar"] for u, info in connected_clients.items()}
                colors = {u: info["color"] for u, info in connected_clients.items()}
                bios = {u: info["bio"] for u, info in connected_clients.items()}

                cursor.execute("SELECT user1, user2 FROM friends WHERE (user1 = %s OR user2 = %s) AND status = 'accepted'", (current_user, current_user))
                friends = []
                for u1, u2 in cursor.fetchall():
                    friends.append(u2 if u1 == current_user else u1)

                cursor.execute("SELECT user1 FROM friends WHERE user2 = %s AND status = 'pending'", (current_user,))
                requests = [row[0] for row in cursor.fetchall()]

                await websocket.send(json.dumps({
                    "type": "user_list_response", "users": online_users, "friends": friends, "requests": requests,
                    "avatars": avatars, "colors": colors, "bios": bios
                }))

            elif msg_type == "friend_request":
                target = data.get("target")
                if not current_user or not target:
                    continue

                cursor.execute("SELECT public_key FROM users WHERE username = %s", (target,))
                target_user_data = cursor.fetchone()

                if not target_user_data or not target_user_data[0]:
                    await websocket.send(json.dumps({
                        "status": "error",
                        "message": f"'{target}' adlı kullanıcının şifreleme anahtarı bulunamadığı için arkadaşlık isteği gönderilemedi!"
                    }))
                    continue

                cursor.execute("SELECT * FROM friends WHERE (user1=%s AND user2=%s) OR (user1=%s AND user2=%s)", (current_user, target, target, current_user))
                if not cursor.fetchone():
                    cursor.execute("INSERT INTO friends (user1, user2, status) VALUES (%s, %s, 'pending')", (current_user, target))
                    
                    await websocket.send(json.dumps({
                        "status": "success",
                        "message": f"'{target}' adlı kişiye arkadaşlık isteği gönderildi."
                    }))

                    if target in connected_clients:
                        await connected_clients[target]["websocket"].send(json.dumps({
                            "type": "friend_request_received", 
                            "sender": current_user
                        }))
                    await broadcast_user_lists()
                else:
                    await websocket.send(json.dumps({
                        "status": "error",
                        "message": "Bu kullanıcıyla zaten arkadaşsınız veya bekleyen bir isteğiniz var."
                    }))

            elif msg_type == "accept_friend":
                sender = data.get("sender")
                cursor.execute(
                    "UPDATE friends SET status = 'accepted' WHERE user1 = %s AND user2 = %s",
                    (sender, current_user),
                )
                await broadcast_user_lists()

            elif msg_type == "reject_friend":
                sender = data.get("sender")
                cursor.execute("DELETE FROM friends WHERE user1 = %s AND user2 = %s", (sender, current_user))
                await broadcast_user_lists()

            elif msg_type == "update_profile":
                bio = data.get("bio", "")
                avatar = data.get("avatar", "")
                color = data.get("color", "")
                theme = data.get("theme", "")
                
                cursor.execute("UPDATE users SET bio=%s, avatar=%s, color=%s, theme=%s WHERE username=%s", (bio, avatar, color, theme, current_user))
                
                if current_user in connected_clients:
                    connected_clients[current_user]["bio"] = bio
                    connected_clients[current_user]["avatar"] = avatar
                    connected_clients[current_user]["color"] = color

                await broadcast_user_lists()

            elif msg_type == "get_key":
                target = data.get("target")
                cursor.execute("SELECT public_key FROM users WHERE username = %s", (target,))
                res = cursor.fetchone()
                if res:
                    await websocket.send(json.dumps({"type": "key_response", "username": target, "public_key": res[0]}))

            elif msg_type == "msg":
                target = data.get("target")
                sender = current_user
                enc_key = data.get("encrypted_key")
                nonce = data.get("nonce")
                ciphertext = data.get("ciphertext")
                color = data.get("color")

                cursor.execute("INSERT INTO messages (sender, target, encrypted_key, nonce, ciphertext, color) VALUES (%s, %s, %s, %s, %s, %s)", 
                              (sender, target, enc_key, nonce, ciphertext, color))

                if target in connected_clients:
                    await connected_clients[target]["websocket"].send(message)

    except websockets.exceptions.ConnectionClosed:
        pass
    finally:
        if current_user and current_user in connected_clients:
            del connected_clients[current_user]
            await broadcast_user_lists()

async def main():
    port = int(os.environ.get("PORT", 8765))
    # Ping mekanizması eklenerek bağlantının koptuğu anlık olarak algılanır
    async with websockets.serve(handler, "0.0.0.0", port, ping_interval=20, ping_timeout=10):
        await asyncio.Future()

if __name__ == "__main__":
    asyncio.run(main())
