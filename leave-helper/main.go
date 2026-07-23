package main

import (
	"context"
	"errors"
	"flag"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"time"

	"github.com/gotd/td/telegram/peers"
	"github.com/gotd/td/tg"
	"github.com/iyear/tdl/core/storage"
	coretclient "github.com/iyear/tdl/core/tclient"
	"github.com/iyear/tdl/core/util/tutil"
	"go.etcd.io/bbolt"
)

type boltStorage struct { db *bbolt.DB; namespace []byte }

func (s *boltStorage) Get(ctx context.Context, key string) ([]byte, error) {
	var value []byte
	err := s.db.View(func(tx *bbolt.Tx) error {
		bucket := tx.Bucket(s.namespace)
		if bucket == nil || bucket.Get([]byte(key)) == nil { return storage.ErrNotFound }
		value = append([]byte(nil), bucket.Get([]byte(key))...)
		return nil
	})
	return value, err
}
func (s *boltStorage) Set(ctx context.Context, key string, value []byte) error {
	return s.db.Update(func(tx *bbolt.Tx) error { b, err := tx.CreateBucketIfNotExists(s.namespace); if err != nil { return err }; return b.Put([]byte(key), value) })
}
func (s *boltStorage) Delete(ctx context.Context, key string) error {
	return s.db.Update(func(tx *bbolt.Tx) error { b := tx.Bucket(s.namespace); if b == nil { return nil }; return b.Delete([]byte(key)) })
}

func openStorage(path, namespace string) (*boltStorage, error) {
	if err := os.MkdirAll(path, 0755); err != nil { return nil, err }
	db, err := bbolt.Open(filepath.Join(path, namespace), 0600, nil)
	if err != nil { return nil, err }
	return &boltStorage{db: db, namespace: []byte(namespace)}, nil
}

func main() {
	storagePath := flag.String("storage", "", "tdl bolt data directory")
	namespace := flag.String("namespace", "default", "tdl namespace")
	identityFile := flag.String("identity-file", "", "write authenticated account identity JSON")
	whoami := flag.Bool("whoami", false, "write authenticated account identity")
	var chats multiFlag
	flag.Var(&chats, "chat", "chat username or id; repeatable")
	flag.Parse()
	if *storagePath == "" || (!*whoami && len(chats) == 0) { fmt.Fprintln(os.Stderr, "--storage and --chat, or --whoami, are required"); os.Exit(2) }

	st, err := openStorage(*storagePath, *namespace); if err != nil { fail(err) }; defer st.db.Close()
	client, err := coretclient.New(context.Background(), coretclient.Options{
		AppID: 15055931,
		AppHash: "021d433426cbb920eeb95164498fe3d3",
		Session: storage.NewSession(st, false),
		ReconnectTimeout: 30 * time.Second,
	}); if err != nil { fail(err) }
	ctx, cancel := context.WithTimeout(context.Background(), 30*time.Minute); defer cancel()
	err = client.Run(ctx, func(ctx context.Context) error {
		status, err := client.Auth().Status(ctx); if err != nil { return err }; if !status.Authorized { return errors.New("tdl session is not authorized") }
		if *whoami {
			users, err := client.API().UsersGetUsers(ctx, []tg.InputUserClass{&tg.InputUserSelf{}}); if err != nil { return err }
			if len(users) != 1 { return errors.New("Telegram tidak mengembalikan identity sesi") }
			user, ok := users[0].(*tg.User); if !ok { return errors.New("identity sesi bukan user biasa") }
			payload := fmt.Sprintf("{\"tdl_user_id\":%d,\"telegram_user_id\":%d,\"username\":%q,\"first_name\":%q}\n", user.ID, user.ID, user.Username, user.FirstName)
			if *identityFile == "" { fmt.Print(payload); return nil }
			if err := os.MkdirAll(filepath.Dir(*identityFile), 0755); err != nil { return err }
			return os.WriteFile(*identityFile, []byte(payload), 0644)
		}
		manager := peers.Options{Storage: storage.NewPeers(st)}.Build(client.API())
		for _, chat := range chats {
			if err := leave(ctx, client.API(), manager, chat); err != nil { fmt.Printf("{\"chat_ref\":%q,\"ok\":false,\"error\":%q}\n", chat, err.Error()); continue }
			fmt.Printf("{\"chat_ref\":%q,\"ok\":true}\n", chat)
		}
		return nil
	})
	if err != nil { fail(err) }
}

func leave(ctx context.Context, api *tg.Client, manager *peers.Manager, chat string) error {
	peer, err := tutil.GetInputPeer(ctx, manager, strings.TrimSpace(chat)); if err != nil { return err }
	raw := peer.InputPeer()
	input, ok := raw.(*tg.InputPeerChannel); if !ok { return fmt.Errorf("%s has no channel input peer", chat) }
	_, err = api.ChannelsLeaveChannel(ctx, &tg.InputChannel{ChannelID: input.ChannelID, AccessHash: input.AccessHash})
	return err
}

type multiFlag []string
func (m *multiFlag) String() string { return strings.Join(*m, ",") }
func (m *multiFlag) Set(v string) error { *m = append(*m, v); return nil }
func fail(err error) { fmt.Fprintln(os.Stderr, err); os.Exit(1) }

var _ storage.Storage = (*boltStorage)(nil)
