package com.naufal.raspbx;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.app.Service;
import android.content.Intent;
import android.os.Build;
import android.os.IBinder;
import android.os.PowerManager;
import java.io.*;
import java.net.HttpURLConnection;
import java.net.URL;
import java.security.MessageDigest;
import java.util.*;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicBoolean;

public class PbxService extends Service {
    public static volatile String state="Belum berjalan. Tekan Mulai.";
    public static volatile boolean ready=false;
    private final AtomicBoolean running=new AtomicBoolean(false);
    private volatile Process server;
    private volatile boolean stopRequested=false;
    private PowerManager.WakeLock wake;
    private File base;
    private static final String ROOTFS_SHA="c227dd7e230d9e20bc60ab82693ec256bd2172e7e8c3d274e809ef7505c19a8d";
    @Override public void onCreate(){super.onCreate();base=new File(getFilesDir(),"raspbx");base.mkdirs();}
    @Override public int onStartCommand(Intent intent,int flags,int id){
        if(intent!=null&&"stop".equals(intent.getAction())){new Thread(()->stopPbx()).start();return START_NOT_STICKY;}
        foreground();
        if(running.compareAndSet(false,true)){stopRequested=false;new Thread(()->startPbx(),"RasPBX-supervisor").start();}
        return START_NOT_STICKY;
    }
    private void foreground(){
        NotificationManager manager=(NotificationManager)getSystemService(NOTIFICATION_SERVICE);
        manager.createNotificationChannel(new NotificationChannel("pbx","RasPBX Server",NotificationManager.IMPORTANCE_LOW));
        Intent open=new Intent(this,MainActivity.class);
        PendingIntent pending=PendingIntent.getActivity(this,0,open,PendingIntent.FLAG_UPDATE_CURRENT|PendingIntent.FLAG_IMMUTABLE);
        Notification notification=new Notification.Builder(this,"pbx").setContentTitle("RasPBX Android")
            .setContentText("Server berjalan di HP. Buka aplikasi untuk status dan Hentikan.")
            .setSmallIcon(android.R.drawable.stat_sys_phone_call).setContentIntent(pending).setOngoing(true).build();
        startForeground(101,notification);
    }
    private void startPbx(){
        try{
            if(Build.SUPPORTED_32_BIT_ABIS.length==0)throw new IOException("HP tidak mendukung ARM 32-bit yang diperlukan image ini.");
            wake=((PowerManager)getSystemService(POWER_SERVICE)).newWakeLock(PowerManager.PARTIAL_WAKE_LOCK,"RasPBX:server");wake.acquire();
            prepare();
            if(stopRequested)throw new InterruptedException("Startup dibatalkan");
            state="Memulai database, Asterisk, dan FreePBX...";
            server=guest("/bin/bash","/opt/raspbx-android/guest-supervise.sh").start();
            new Thread(()->{
                while(running.get()&&server!=null&&server.isAlive()){
                    String stage=readStage();
                    if(!stage.isEmpty()&&!"READY".equals(stage))state=stage;
                    if("READY".equals(stage)&&webReady()){ready=true;state="Aktif di HP • FreePBX 8088 • SIP UDP 15060";break;}
                    try{Thread.sleep(1000);}catch(InterruptedException error){return;}
                }
            },"RasPBX-health").start();
            int result=server.waitFor();
            if(running.get())state=stopRequested?"Layanan dihentikan.":"Layanan berhenti (kode "+result+"). Buka Log untuk diagnosis.";
        }catch(Exception error){state=stopRequested?"Layanan dihentikan.":"Gagal: "+error.getMessage();log(error.toString());}
        finally{ready=false;running.set(false);if(wake!=null&&wake.isHeld())wake.release();stopForeground(true);stopSelf();}
    }
    private void prepare()throws Exception{
        for(String folder:new String[]{"rootfs","proot-tmp","shm","tmp"})new File(base,folder).mkdirs();
        File marker=new File(base,"rootfs/.android-export-complete");
        if(!marker.exists()){
            if(base.getUsableSpace()<3500000000L)throw new IOException("Diperlukan sekitar 3,5 GB ruang kosong saat penyiapan pertama.");
            state="Menyalin filesystem RasPBX...";
            File archive=new File(base,"rootfs.tar.gz");MessageDigest digest=MessageDigest.getInstance("SHA-256");
            try(InputStream input=getAssets().open("raspbx-android-armhf.tar.gz");OutputStream out=new FileOutputStream(archive)){
                byte[] buffer=new byte[1024*1024];int size;long copied=0;
                while((size=input.read(buffer))!=-1){if(stopRequested)throw new InterruptedException("Penyiapan dibatalkan");out.write(buffer,0,size);digest.update(buffer,0,size);copied+=size;state="Menyiapkan filesystem: "+(copied/1024/1024)+" / 746 MB";}
            }
            StringBuilder hash=new StringBuilder();for(byte value:digest.digest())hash.append(String.format(Locale.US,"%02x",value&255));
            if(!ROOTFS_SHA.equals(hash.toString()))throw new IOException("Checksum filesystem tidak cocok.");
            state="Mengekstrak filesystem RasPBX...";
            Process extract=new ProcessBuilder("/system/bin/tar","-xzf",archive.getAbsolutePath(),"-C",new File(base,"rootfs").getAbsolutePath())
                .redirectErrorStream(true).redirectOutput(ProcessBuilder.Redirect.appendTo(new File(base,"runtime.log"))).start();
            if(extract.waitFor()!=0)throw new IOException("Ekstraksi gagal; lihat Log.");
            marker.createNewFile();archive.delete();
            if(stopRequested)throw new InterruptedException("Startup dibatalkan");
        }
        File scripts=new File(base,"rootfs/opt/raspbx-android");scripts.mkdirs();
        for(String name:new String[]{"guest-supervise.sh","guest-stop.sh","guest-setup.php","guest-collect.php"}){
            try(InputStream in=getAssets().open(name);OutputStream out=new FileOutputStream(new File(scripts,name))){byte[] b=new byte[8192];int n;while((n=in.read(b))!=-1)out.write(b,0,n);}
        }
        new File(scripts,"startup-state").delete();
    }
    private ProcessBuilder guest(String... args){
        String nativeDir=getApplicationInfo().nativeLibraryDir;
        List<String> command=new ArrayList<>(Arrays.asList(nativeDir+"/libproot.so","--link2symlink","--kill-on-exit","--sysvipc","-0",
            "-r",new File(base,"rootfs").getAbsolutePath(),"-b","/dev","-b","/proc","-b","/sys",
            "-b",new File(base,"shm").getAbsolutePath()+":/dev/shm","-b",new File(base,"tmp").getAbsolutePath()+":/tmp","-w","/root",
            "/usr/bin/env","-i","HOME=/root","PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin","TERM=xterm","LANG=C"));
        command.add("RASPBX_WIFI_IP="+MainActivity.wifiAddress(this));
        command.addAll(Arrays.asList(args));
        ProcessBuilder builder=new ProcessBuilder(command);Map<String,String> env=builder.environment();
        env.put("LD_LIBRARY_PATH",nativeDir);env.put("PROOT_TMP_DIR",new File(base,"proot-tmp").getAbsolutePath());
        env.put("PROOT_LOADER",nativeDir+"/libproot-loader.so");env.put("PROOT_LOADER_32",nativeDir+"/libproot-loader32.so");env.put("PROOT_NO_SECCOMP","1");
        builder.redirectErrorStream(true).redirectOutput(ProcessBuilder.Redirect.appendTo(new File(base,"runtime.log")));return builder;
    }
    private boolean webReady(){
        HttpURLConnection connection=null;
        try{connection=(HttpURLConnection)new URL("http://127.0.0.1:8088/admin/").openConnection();connection.setConnectTimeout(2000);connection.setReadTimeout(5000);return connection.getResponseCode()==200;}
        catch(Exception error){return false;}finally{if(connection!=null)connection.disconnect();}
    }
    private String readStage(){
        try(BufferedReader reader=new BufferedReader(new FileReader(new File(base,"rootfs/opt/raspbx-android/startup-state")))){
            String line=reader.readLine();return line==null?"":line.trim();
        }catch(IOException error){return "";}
    }
    private void stopPbx(){
        stopRequested=true;
        state="Menghentikan layanan dengan aman...";ready=false;
        try{if(server!=null&&server.isAlive()){Process stop=guest("/bin/bash","/opt/raspbx-android/guest-stop.sh").start();stop.waitFor(45,TimeUnit.SECONDS);server.waitFor(10,TimeUnit.SECONDS);}}
        catch(Exception error){log(error.toString());}
        state="Layanan dihentikan.";
    }
    private void log(String message){try(FileWriter writer=new FileWriter(new File(base,"runtime.log"),true)){writer.write(message+"\n");}catch(IOException ignored){}}
    @Override public IBinder onBind(Intent intent){return null;}
}
